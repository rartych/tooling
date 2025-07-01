import os
import sys
import json
import requests
from datetime import datetime
from github import Github
from markdown import markdown
from bs4 import BeautifulSoup
import re
import yaml

token = os.environ.get('GITHUB_TOKEN')
pr_url = os.environ.get('PR_URL')
issue_numbera= os.environ.get('ISSUE_NUMBER')
include_diff = os.environ.get('INCLUDE_DIFF', 'true').lower() == 'true'

def parse_pr_url(pr_url):
    """Parse PR URL to extract owner, repo, and PR number"""
    pattern = r'https://github\.com/([^/]+)/([^/]+)/pull/(\d+)'
    match = re.match(pattern, pr_url)
    if not match:
        raise ValueError(f"Invalid PR URL format: {pr_url}")
    return match.groups()

def get_pr_files(token, owner, repo, pr_number):
    """Get list of changed files in a PR"""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github+json'
    }
              
    # Get PR details
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = requests.get(pr_url, headers=headers, verify=False)
    pr_response.raise_for_status()
    pr_data = pr_response.json()
              
    # Get PR files
    files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    files_response = requests.get(files_url, headers=headers, verify=False)
    files_response.raise_for_status()
    files_data = files_response.json()
              
    return pr_data, files_data

def get_pr_files(token, owner, repo, pr_number):
    """Get list of changed files in a PR"""
    headers = {
        'Authorization': f'token {token}',
        'Accept': 'application/vnd.github+json'
    }
              
    # Get PR details
    pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}"
    pr_response = requests.get(pr_url, headers=headers, verify=False)
    pr_response.raise_for_status()
    pr_data = pr_response.json()
              
    # Get PR files
    files_url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}/files"
    files_response = requests.get(files_url, headers=headers, verify=False)
    files_response.raise_for_status()
    files_data = files_response.json()
              
    return pr_data, files_data
  
def analyse_OAS (url):
    OAS = yaml.safe_load(requests.get(url, verify=False).text)
    analysis_result=""
    OAS_info=OAS.get('info', {})
    analysis_result="API Title: "+ OAS_info.get('title')
    analysis_result=analysis_result +"\nAPI version: "+ OAS_info.get('version')
    analysis_result=analysis_result +"\nCommonalities version: "+ str(OAS_info.get('x-camara-commonalities'))
    external_docs=OAS.get('externalDocs', {})
    print (external_docs)
    check_mark_unicode = "\u2705"
    cross_mark_unicode = "u\274C"

    return analysis_result

def main():
    """Main function to run the analysis."""
    try:
        # Parse PR URL
        owner, repo, pr_number = parse_pr_url(pr_url)
        print(f"Analyzing PR #{pr_number} from {owner}/{repo}")
                  
        # Get PR files
        pr_data, files_data = get_pr_files(token, owner, repo, pr_number)
                  
        # Create comment
        
        for f in files_data:
            print (f['filename'], f['raw_url'] )             
            if f['filename']=='CHANGELOG.md':
                print ('### Changelog checks')
                # changelog_results= analyse_changelog(f['raw_url'])
                print (changelog_results)

            if 'code/API_definitions/' in f['filename']:
                print ('### OAS checks '+ f['filename'])
                OAS_results= analyse_OAS(f['raw_url'])
                print (OAS_results)
            
    except Exception as e:
        print(f"Error: {e}")

  if __name__ == "__main__":
    main()
