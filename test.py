import boto3
s3 = boto3.client('s3')
with open('testfile.txt', 'w') as f:
    f.write('test')

with open('testfile.txt', 'rb') as f:
    s3.upload_fileobj(f, 'echosu-s3-v2', 'static/testfile.txt')
