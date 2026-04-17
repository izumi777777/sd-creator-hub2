"""予約済み画像生成ジョブの実行（ポーリング）。"""

from __future__ import annotations

import logging
from datetime import datetime

from app import db
from app.models.character import Character
from app.models.scheduled_image_job import ScheduledImageJob
from app.models.story import Story
from app.services.story_sd_generation import generate_chapter_images

logger = logging.getLogger(__name__)


def _claim_job(job: ScheduledImageJob, now: datetime) -> bool:
    """pending のままなら running に更新。競合時は False。"""
    updated = (
        ScheduledImageJob.query.filter(
            ScheduledImageJob.id == job.id,
            ScheduledImageJob.status == ScheduledImageJob.STATUS_PENDING,
        ).update(
            {
                "status": ScheduledImageJob.STATUS_RUNNING,
                "started_at": now,
            },
            synchronize_session=False,
        )
    )
    db.session.commit()
    return updated == 1


def run_due_jobs(*, max_per_tick: int = 3) -> int:
    """
    scheduled_at が過去の pending ジョブを最大 max_per_tick 件まで実行する。

    Returns:
        このティックで完了または失敗にした件数。
    """
    now = datetime.utcnow()
    due = (
        ScheduledImageJob.query.filter(
            ScheduledImageJob.status == ScheduledImageJob.STATUS_PENDING,
            ScheduledImageJob.scheduled_at <= now,
        )
        .order_by(ScheduledImageJob.scheduled_at.asc())
        .limit(max_per_tick)
        .all()
    )
    done = 0
    for job in due:
        if not _claim_job(job, now):
            continue
        db.session.refresh(job)
        story = Story.query.get(job.story_id)
        character = Character.query.get(job.character_id)
        if not story or not character:
            job.status = ScheduledImageJob.STATUS_FAILED
            job.error_message = "ストーリーまたはキャラが見つかりません。"
            job.completed_at = datetime.utcnow()
            db.session.commit()
            done += 1
            continue
        if story.character_id != job.character_id:
            job.status = ScheduledImageJob.STATUS_FAILED
            job.error_message = "予約時のキャラとストーリーのキャラが一致しません。"
            job.completed_at = datetime.utcnow()
            db.session.commit()
            done += 1
            continue
        seed = job.seed if job.seed is not None else -1
        bs = getattr(job, "batch_size", None) or 1
        ni = getattr(job, "n_iter", None) or 1
        cfg = getattr(job, "cfg_scale", None)
        sampler = getattr(job, "sampler_name", None)
        enable_hr = getattr(job, "enable_hr", None)
        hr_scale = getattr(job, "hr_scale", None)
        hr_denoising = getattr(job, "hr_denoising_strength", None)
        hr_2steps = getattr(job, "hr_second_pass_steps", None)
        hr_up = getattr(job, "hr_upscaler", None)
        try:
            include_speech = getattr(
                job, "overlay_include_speech", True
            )
            preset_idx = getattr(job, "speech_preset_index", None)
            speech_override = None
            if preset_idx is not None and isinstance(preset_idx, int):
                if 0 <= preset_idx < Story.SPEECH_PRESET_SLOTS:
                    t = story.get_speech_presets()[preset_idx].strip()
                    speech_override = t if t else None
            generate_chapter_images(
                story,
                character,
                job.ch_no,
                job.variant_index,
                steps=job.steps or 20,
                width=job.width or 512,
                height=job.height or 768,
                seed=seed,
                batch_size=int(bs),
                n_iter=int(ni),
                cfg_scale=cfg,
                sampler_name=sampler,
                enable_hr=enable_hr,
                hr_scale=hr_scale,
                hr_denoising_strength=hr_denoising,
                hr_second_pass_steps=hr_2steps,
                hr_upscaler=hr_up,
                overlay_include_speech=bool(include_speech),
                speech_bottom_override=speech_override,
            )
            job.status = ScheduledImageJob.STATUS_DONE
            job.error_message = None
        except Exception as e:
            logger.exception("schedule_worker: job %s failed", job.id)
            job.status = ScheduledImageJob.STATUS_FAILED
            job.error_message = str(e)[:8000]
        job.completed_at = datetime.utcnow()
        db.session.commit()
        done += 1
    return done
