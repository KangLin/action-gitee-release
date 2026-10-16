#!/usr/bin/env python
# coding:utf-8
import os
import glob
import requests
import time
from requests_toolbelt import MultipartEncoder
from functools import wraps

API_BASE="https://codeberg.org/api/v1"

retry_times = os.environ.get("codeberg_upload_retry_times", "0")
try:
    retry_times = int(retry_times)
except Exception:
    retry_times = 0

def Retry(retry, include_exceptions = [Exception], exclude_exceptions = [ValueError], sleep = 1):
    def decoratedRetry(func):
        def checkRun(retry, *args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if no_catch(e, exclude_exceptions) or not need_catch(e, include_exceptions):
                    raise e
                if(retry == 0):
                    raise e
                else:
                    print('error catched:', e)
                    if sleep > 0:
                        time.sleep(sleep)
                    return checkRun(retry-1, *args, **kwargs)
                    
        @wraps(func)      
        def run(*args, **kwargs):
            return checkRun(retry, *args, **kwargs)
        return run
    return decoratedRetry

def need_catch(exception, include_exceptions):
    for ex in include_exceptions:
        if isinstance(exception, ex):
            return True
    return False
    
def no_catch(exception, exclude_exceptions):
    for ex in exclude_exceptions:
        if isinstance(exception, ex):
            return True
    return False

class codeberg:
    def __init__(self, owner, token):
        self.owner = owner
        self.token = token

    def _auth_headers(self, extra=None):
        headers = {'Authorization': f'token {self.token}'}
        if extra:
            headers.update(extra)
        return headers

    def create_release(self, repo, tag_name, name, body = '-', target_commitish = 'master'):
        url = f'{API_BASE}/repos/{self.owner}/{repo}/releases'
        data = {
            'access_token': self.token,
            'tag_name': tag_name,
            'name': name,
            'body': body,
            'target_commitish': target_commitish,
        }
        response = requests.post(url, data=data, headers=self._auth_headers())
        res = response.json()
        if response.status_code != 201:
            return False, res["message"] if "message" in res else f"Response status_code is {response.status_code}"
        else:
            if "id" in res:
                return True, res["id"]
            else:
                return False, "No 'id' in response"

    # See: https://codeberg.org/api/swagger#/repository/repoCreateReleaseAttachment
    @Retry(retry_times)
    def upload_asset(self, repo, release_id, file_name, file_path):
        if not os.path.isfile(file_path):
            raise ValueError('file_path not exists: ' + file_path)

        with open(file_path, 'rb') as f:
            fields = {'attachment': (file_name, f, 'application/octet-stream')}
            m = MultipartEncoder(fields=fields)
            url = f"{API_BASE}/repos/{self.owner}/{repo}/releases/{release_id}/assets"
            response = requests.post(
                url,
                data=m,
                headers=self._auth_headers({'Content-Type': m.content_type}),
            )

        res = response.json()
        if response.status_code != 201:
            return False, res["message"] if "message" in res else f"Response status_code is {response.status_code}"
        else:
            if "browser_download_url" in res:
                return True, res["browser_download_url"]
            return False, "No 'browser_download_url' in response"

    # See: https://codeberg.org/api/swagger#/repository/repoGetReleaseByTag
    def get_release_by_tag(self, repo, tag_name):
        url = f'{API_BASE}/repos/{self.owner}/{repo}/releases/tags/{tag_name}'
        response = requests.get(url, headers=self._auth_headers())
        res = response.json()
        if response.status_code != 200:
            return False, res.get("message", f"Status code {response.status_code}")
        if "id" in res:
            return True, res["id"]
        else:
            return False, "No release id found"

    # See: https://codeberg.org/api/swagger#/repository/repoListReleaseAttachments
    def get_asset_id(self, repo, release_id, filename):
        url = f'{API_BASE}/repos/{self.owner}/{repo}/releases/{release_id}/assets'
        response = requests.get(url, , headers=self._auth_headers("per_page": 100))
        res = response.json()
        if response.status_code != 200:
            return False, res.get("message", f"Status code {response.status_code}")
        for asset in res:
            if asset['name'] == filename:
                return True, asset['id']
        return False, "Asset not found"

    @Retry(retry_times)
    def update_asset(self, repo, tag_name, filename, new_file_path):
        success, release_id = self.get_release_by_tag(repo, tag_name)
        if not success:
            return False, release_id
        
        success, asset_id = self.get_asset_id(repo, release_id, filename)
        if not success:
            return False, asset_id
        
        success, msg = self.delete_asset(repo, release_id, asset_id)
        if not success:
            return False, msg
        
        return self.upload_asset(repo, release_id, file_name=filename, file_path=new_file_path)

    def delete_release_by_tag(self, repo, tag_name):
        success, release_id = self.get_release_by_tag(repo, tag_name)
        if not success:
            return False, release_id
        return self.delete_release(repo, release_id)

    def delete_release(self, repo, release_id):
        url = f'{API_BASE}/repos/{self.owner}/{repo}/releases/{release_id}'
        params = {'access_token': self.token}
        response = requests.delete(url, params=params)
        if response.status_code == 204:
            return True, "Release deleted successfully"
        else:
            res = response.json()
            return False, res.get("message", f"Status code {response.status_code}")

    def delete_asset_by_filename(self, repo, tag_name, filename):
        success, release_id = self.get_release_by_tag(repo, tag_name)
        if not success:
            return False, release_id
        
        success, asset_id = self.get_asset_id(repo, release_id, filename)
        if not success:
            return False, asset_id
        return self.delete_asset(repo, release_id, asset_id)

    def delete_asset(self, repo, release_id, asset_id):
        url = f'{API_BASE}/repos/{self.owner}/{repo}/releases/{release_id}/assets/{asset_id}'
        params = {'access_token': self.token}
        response = requests.delete(url, params=params)
        if response.status_code == 204:
            return True, "Asset deleted successfully"
        else:
            res = response.json()
            return False, res.get("message", f"Status code {response.status_code}")

def get(key):
    val = os.environ.get(key)
    if not val:
        raise ValueError(f'{key} not set in the environment')
    return val
    
def set_result(name, result):
    print("result: ", f"{name}={result}")
    github_out = os.environ.get("GITHUB_OUTPUT")
    if github_out:
        with open(github_out, 'a', encoding='utf-8') as output:
            if '\n' not in str(result):
                output.write(f"{name}={result}\n")
                print(f"{name}={result}\n")
            else:
                delimiter = 'EOF'
                output.write(f"{name}<<{delimiter}\n{result}\n{delimiter}\n")
                print(f"{name}<<{delimiter}\n{result}\n{delimiter}\n")
                
def upload_assets(codeberg_files, codeberg_client, codeberg_repo, codeberg_release_id):
    result = []
    uploaded_path = set()
    for file_path_pattern in codeberg_files:
        file_path_pattern = file_path_pattern.strip()
        recursive = True if "**" in file_path_pattern else False
        files = glob.glob(file_path_pattern, recursive = recursive)
        if len(files) == 0:
            raise ValueError('file_path_pattern does not match: ' + file_path_pattern)
        for file_path in files:
            if file_path in uploaded_path or os.path.isdir(file_path):
                continue
            success, msg = codeberg_client.upload_asset(codeberg_repo, codeberg_release_id, file_name = os.path.basename(file_path), file_path = file_path)
            if not success:
                raise Exception("Upload file asset failed: " + msg)
            result.append(msg)
            uploaded_path.add(file_path)
    return result

# See: https://codeberg.org/api/swagger#/repository/repoCreateRelease
def create_release():
    codeberg_owner = get('codeberg_owner')
    codeberg_token = get('codeberg_token')
    codeberg_repo = get('codeberg_repo')
    codeberg_tag_name = get('codeberg_tag_name')
    codeberg_release_name = get('codeberg_release_name')
    codeberg_release_body = get('codeberg_release_body')
    codeberg_target_commitish = get('codeberg_target_commitish')
    
    codeberg_files = os.environ.get('codeberg_files')
    if codeberg_files:
        codeberg_files = codeberg_files.strip().split("\n")
    else:
        codeberg_file_name = os.environ.get('codeberg_file_name')
        codeberg_file_path = os.environ.get('codeberg_file_path')
        if (codeberg_file_name and not codeberg_file_path) or (codeberg_file_path and not codeberg_file_name):
            raise ValueError('codeberg_file_name and codeberg_file_path should be set together')
        if codeberg_file_path and not os.path.isfile(codeberg_file_path):
            raise ValueError('codeberg_file_path not exists: ' + codeberg_file_path)
    
    codeberg_client = codeberg(owner = codeberg_owner, token = codeberg_token)
    success, release_id = codeberg_client.create_release(repo = codeberg_repo, tag_name = codeberg_tag_name, name = codeberg_release_name,
                body = codeberg_release_body, target_commitish = codeberg_target_commitish)
    if success:
        print(f"Release created successfully with ID: {release_id}")
        set_result("release-id", release_id)
        
        # Upload files if provided
        if codeberg_files:
            result = upload_assets(codeberg_files, codeberg_client, codeberg_repo, release_id)
            if result:
                set_result("download-url", '\n'.join(result))
        elif codeberg_file_path:
            success, msg = codeberg_client.upload_asset(codeberg_repo, release_id, file_name = codeberg_file_name, file_path = codeberg_file_path)
            if not success:
                raise Exception("Upload file asset failed: " + msg)
            set_result("download-url", msg)
    else:
        raise Exception("Create release failed: " + str(release_id))

def upload_asset():
    codeberg_owner = get('codeberg_owner')
    codeberg_repo = get('codeberg_repo')
    codeberg_token = get('codeberg_token')
    codeberg_files = os.environ.get('codeberg_files')
    
    codeberg_client = codeberg(owner = codeberg_owner, token = codeberg_token)

    codeberg_release_id = os.environ.get('codeberg_release_id')
    if not codeberg_release_id:
        codeberg_tag_name = get('codeberg_tag_name')
        success, codeberg_release_id = codeberg_client.get_release_by_tag(codeberg_repo, codeberg_tag_name)
        if not success:
            raise Exception(f"Failed to get release by tag {codeberg_tag_name}")

    if codeberg_files:
        codeberg_files = codeberg_files.strip().split("\n")
        result = upload_assets(codeberg_files, codeberg_client, codeberg_repo, codeberg_release_id)
        set_result("download-url", '\n'.join(result))
    else:
        codeberg_file_name = get('codeberg_file_name')
        codeberg_file_path = get('codeberg_file_path')
        if codeberg_file_path and not os.path.isfile(codeberg_file_path):
            raise ValueError('codeberg_file_path not exists: ' + codeberg_file_path)
        success, msg = codeberg_client.upload_asset(codeberg_repo, codeberg_release_id, file_name = codeberg_file_name, file_path = codeberg_file_path)
        if not success:
            raise Exception("Upload file asset failed: " + msg)
        set_result("download-url", msg)

def delete_release():
    codeberg_owner = get('codeberg_owner')
    codeberg_repo = get('codeberg_repo')
    codeberg_token = get('codeberg_token')
    codeberg_tag_name = get('codeberg_tag_name')
    
    codeberg_client = codeberg(owner=codeberg_owner, token=codeberg_token)
    success, msg = codeberg_client.delete_release_by_tag(codeberg_repo, codeberg_tag_name)
    if not success:
        raise Exception("Delete release failed: " + msg)
    print("Release deleted successfully")

def delete_asset():
    codeberg_owner = get('codeberg_owner')
    codeberg_repo = get('codeberg_repo')
    codeberg_token = get('codeberg_token')
    codeberg_tag_name = get('codeberg_tag_name')
    
    codeberg_delete_assets = get('codeberg_delete_assets')
    asset_names = [name.strip() for name in codeberg_delete_assets.strip().split('\n') if name.strip()]
    
    codeberg_client = codeberg(owner=codeberg_owner, token=codeberg_token)
    
    for asset_name in asset_names:
        success, msg = codeberg_client.delete_asset_by_filename(codeberg_repo, codeberg_tag_name, asset_name)
        if not success:
            raise Exception(f"Delete asset {asset_name} failed: " + msg)
        print(f"Asset {asset_name} deleted successfully")

def update_asset():
    codeberg_owner = get('codeberg_owner')
    codeberg_repo = get('codeberg_repo')
    codeberg_token = get('codeberg_token')
    codeberg_tag_name = get('codeberg_tag_name')
    codeberg_old_asset_name = get('codeberg_old_asset_name')
    codeberg_new_file_path = get('codeberg_new_file_path')
    
    if not os.path.isfile(codeberg_new_file_path):
        raise ValueError('codeberg_new_file_path not exists: ' + codeberg_new_file_path)
    
    codeberg_client = codeberg(owner=codeberg_owner, token=codeberg_token)
    success, msg = codeberg_client.update_asset(codeberg_repo, codeberg_tag_name, codeberg_old_asset_name, codeberg_new_file_path)
    if not success:
        raise Exception("Update asset failed: " + msg)
    print(f"Asset {codeberg_old_asset_name} updated successfully")
    set_result("download-url", msg)
        
if __name__ == "__main__":
    codeberg_action = os.environ.get("codeberg_action")
    
    if codeberg_action == "create_release":
        create_release()
    elif codeberg_action == "upload_asset":
        upload_asset()
    elif codeberg_action == "delete_release":
        delete_release()
    elif codeberg_action == "delete_asset":
        delete_asset()
    elif codeberg_action == "update_asset":
        update_asset()
    else:
        raise ValueError(f"Unknown action: {codeberg_action}. Supported actions: create_release, upload_asset, delete_release, delete_asset, update_asset")