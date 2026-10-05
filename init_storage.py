from botocore.exceptions import ClientError

from config import S3_BUCKET
from storage import s3


def main() -> None:
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
        print(f"Bucket '{S3_BUCKET}' sudah ada")
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)
        print(f"Bucket '{S3_BUCKET}' dibuat")


if __name__ == "__main__":
    main()
