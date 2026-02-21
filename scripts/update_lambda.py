#!/usr/bin/env python3
import boto3
import zipfile
import io
import os
import subprocess
import tempfile
import shutil

def package_lambda():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    lambda_file = os.path.join(script_dir, '..', 'lambda', 'embeddings_handler.py')
    
    with tempfile.TemporaryDirectory() as tmpdir:
        print("Installing psycopg2-binary...")
        subprocess.run([
            'pip3', 'install', 'psycopg2-binary', '-t', tmpdir, '--quiet'
        ], check=True)
        
        # Copy Lambda function as lambda_function.py
        shutil.copy(lambda_file, os.path.join(tmpdir, 'lambda_function.py'))
        
        # Create zip
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for root, dirs, files in os.walk(tmpdir):
                dirs[:] = [d for d in dirs if not d.endswith(('.dist-info', '__pycache__'))]
                for file in files:
                    if file.endswith('.pyc'):
                        continue
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, tmpdir)
                    zip_file.write(file_path, arcname)
        
        return zip_buffer.getvalue()

def main():
    print("Packaging Lambda function...")
    zip_content = package_lambda()
    
    print("Updating Lambda function code...")
    lambda_client = boto3.client('lambda', region_name='eu-west-2')
    
    # Wait for function to be ready
    waiter = lambda_client.get_waiter('function_active')
    waiter.wait(FunctionName='car-search-embeddings')
    
    # Update code
    lambda_client.update_function_code(
        FunctionName='car-search-embeddings',
        ZipFile=zip_content
    )
    
    print("Waiting for update to complete...")
    waiter.wait(FunctionName='car-search-embeddings')
    
    print("Lambda function updated successfully!")

if __name__ == '__main__':
    main()
