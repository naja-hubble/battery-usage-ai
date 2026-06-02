import os, sys
import csv
import boto3
import concurrent.futures
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
aws_keys_csv_path = "key/ymaeda6_accessKeys.csv"
with open(aws_keys_csv_path, mode='r', encoding='utf-8-sig') as csv_file:
    csv_reader = csv.DictReader(csv_file)
    aws_keys = next(csv_reader)  # Read the first row of the CSV file

aws_session = boto3.Session(
    aws_access_key_id=aws_keys['Access key ID'],
    aws_secret_access_key=aws_keys['Secret access key']
)
s3_client = aws_session.client('s3')
main_path = ""
download_directory = os.path.join(main_path, 'data')
os.makedirs(download_directory, exist_ok=True)

# S3 bucket name and file extension filter
s3_bucket_name = 'rprm-alpha-01'
file_extensions_to_download = ('.PWM',)

# Function to download a file from S3
def download_s3_file(s3_object):
    try:
        s3_key = s3_object['Key']
        if s3_key.endswith(file_extensions_to_download):
            local_file_path = os.path.join(download_directory, s3_key)
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
            s3_client.download_file(s3_bucket_name, s3_key, local_file_path)
            logging.info(f'Successfully downloaded {s3_key}')
    except Exception as e:
        logging.error(f'Error downloading {s3_key}: {e}')

# Use a paginator to handle large result sets from S3
s3_paginator = s3_client.get_paginator('list_objects_v2')
s3_response_iterator = s3_paginator.paginate(Bucket=s3_bucket_name)

# Use ThreadPoolExecutor to download files concurrently
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    download_futures = []
    for s3_page in s3_response_iterator:
        for s3_object in s3_page.get('Contents', []):
            download_futures.append(executor.submit(download_s3_file, s3_object))

    # Ensure all futures are completed and handle any exceptions
    for future in concurrent.futures.as_completed(download_futures):
        try:
            future.result()
        except Exception as e:
            logging.error(f'Error in future: {e}')
