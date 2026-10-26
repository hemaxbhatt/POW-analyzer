"""
Signed upload URL generation + fetching uploaded files from AWS S3.
Replaces app/ingestion.py's YouTube-downloading responsibility with
direct-upload handling.

Requires these environment variables to be set (see .env at project
root, loaded via python-dotenv in main.py):
  AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY
  AWS_REGION
  S3_BUCKET_NAME
"""

import os
import uuid
from pathlib import Path

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

AWS_REGION = os.environ["AWS_REGION"]
S3_BUCKET_NAME = os.environ["S3_BUCKET_NAME"]

# boto3 automatically picks up AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
# from the environment -- no need to pass them explicitly here.
#
# signature_version="s3v4" + explicit endpoint_url is REQUIRED for
# buckets using the newer "account regional namespace" naming style
# (names with a numeric/region suffix, e.g. "mybucket-123456789-ap-
# south-1-xx"). Without this, boto3 generates URLs against the generic
# s3.amazonaws.com host, which these buckets reject with a 301/
# TemporaryRedirect pointing at their real regional hostname.
_s3_client = boto3.client(
    "s3",
    region_name=AWS_REGION,
    endpoint_url=f"https://s3.{AWS_REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)

UPLOAD_URL_EXPIRY_SECONDS = 15 * 60  # 15 minutes

ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime"}
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png"}
MAX_VIDEO_SIZE_BYTES = 500 * 1024 * 1024   # 500 MB
MAX_PHOTO_SIZE_BYTES = 15 * 1024 * 1024    # 15 MB


def create_upload_urls(student_id: str, task_id: str) -> dict:
    """
    Generates a new submission_id and pre-signed PUT URLs for both the
    video and the required clear photo. The portal calls this first,
    then uploads directly to S3 using these URLs (no file ever passes
    through this backend).
    """
    submission_id = str(uuid.uuid4())

    video_key = f"submissions/{student_id}/{submission_id}/video.mp4"
    photo_key = f"submissions/{student_id}/{submission_id}/photo.jpg"

    video_url = _s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": S3_BUCKET_NAME,
            "Key": video_key,
            "ContentType": "video/mp4",
        },
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )
    photo_url = _s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": S3_BUCKET_NAME,
            "Key": photo_key,
            "ContentType": "image/jpeg",
        },
        ExpiresIn=UPLOAD_URL_EXPIRY_SECONDS,
    )

    return {
        "submission_id": submission_id,
        "video_upload_url": video_url,
        "photo_upload_url": photo_url,
        "expires_in_minutes": UPLOAD_URL_EXPIRY_SECONDS // 60,
    }


def download_submission_files(student_id: str, submission_id: str) -> dict:
    """
    Called AFTER the portal confirms both files were uploaded. Pulls the
    files from S3 down to local disk (in the same data/<job_id>/
    structure the rest of the pipeline already expects), so
    ingestion.py's extract_audio/sample_frames functions work unchanged.
    """
    job_dir = DATA_DIR / submission_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_key = f"submissions/{student_id}/{submission_id}/video.mp4"
    photo_key = f"submissions/{student_id}/{submission_id}/photo.jpg"

    # Check existence + size before downloading (never trust the
    # client's claims about what it uploaded).
    try:
        video_head = _s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=video_key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            raise FileNotFoundError("Video not found in storage -- upload may not have completed.")
        raise

    try:
        photo_head = _s3_client.head_object(Bucket=S3_BUCKET_NAME, Key=photo_key)
    except ClientError as e:
        if e.response["Error"]["Code"] == "404":
            raise FileNotFoundError("Photo not found in storage -- upload may not have completed.")
        raise

    if video_head["ContentLength"] > MAX_VIDEO_SIZE_BYTES:
        raise ValueError(f"Video exceeds max size of {MAX_VIDEO_SIZE_BYTES} bytes.")
    if photo_head["ContentLength"] > MAX_PHOTO_SIZE_BYTES:
        raise ValueError(f"Photo exceeds max size of {MAX_PHOTO_SIZE_BYTES} bytes.")

    video_path = str(job_dir / "source.mp4")
    photo_path = str(job_dir / "photo.jpg")

    _s3_client.download_file(S3_BUCKET_NAME, video_key, video_path)
    _s3_client.download_file(S3_BUCKET_NAME, photo_key, photo_path)

    return {
        "job_id": submission_id,
        "job_dir": str(job_dir),
        "video_path": video_path,
        "photo_path": photo_path,
    }