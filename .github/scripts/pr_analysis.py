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

def analyse_changelog (url):
    html = markdown(requests.get(url, verify=False).text, output_format="html5")
    soup = BeautifulSoup(html, "html.parser")

   # Find all elements in order
    all_elements = soup.find_all(['h1', 'a'])
    
    results = {}
    current_h1 = None
    current_links = []
    
    for element in all_elements:
        if element.name == 'h1':
            # Save previous section if it exists
            if current_h1:
                results[current_h1] = current_links
            
            # Start new section
            current_h1 = element.get_text().strip()
            current_links = []
            
        elif element.name == 'a':
            href = element.get('href')
            text = element.get_text()
            if href and current_h1:
                current_links.append({
                    'text': text,
                    'url': href,
                    'type': 'link'
                })
        
        elif element.name == 'img':
            src = element.get('src')
            alt = element.get('alt', '')
            if src and current_h1:
                current_links.append({
                    'text': alt,
                    'url': src,
                    'type': 'image'
                })
    
    # Don't forget the last section
    if current_h1:
        results[current_h1] = current_links

    rx_pattern = r'^r(\d+)\.(\d+)'
    analysis_result=""
    check_mark_unicode = "\u2705"
    cross_mark_unicode = "u\274C"
    for h1_title, links in results.items():
        release_match=False
        analysis_result=analysis_result + "\n=== {} ===".format(h1_title)
        if not links:
           analysis_result=analysis_result +"\n  No links found"
        else:
            for link in links:
                match = re.match(rx_pattern, h1_title)                
                if match:
                    release_match=True
                    if h1_title in link['url']:                       
                        # print(f"{check_mark_unicode}  {link['type'].title()}: '{link['text']}' -> {link['url']}")
                        analysis_result=analysis_result + "\n" + f"{check_mark_unicode}  {link['type'].title()}: '{link['text']}' -> {link['url']}"
                    else:
                        analysis_result=analysis_result + "\n" + f"{cross_mark_unicode}  {link['type'].title()}: '{link['text']}' -> {link['url']}"
        if not release_match:
            analysis_result=analysis_result + "\n" +f"{check_mark_unicode} No release number in the header"
    return analysis_result

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
    token = os.environ.get('GITHUB_TOKEN')
    pr_url = os.environ.get('PR_URL')
    issue_number= os.environ.get('ISSUE_NUMBER')
    include_diff = os.environ.get('INCLUDE_DIFF', 'true').lower() == 'true'
    try:
        print(f"Analyzing PR #{pr_url}")
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
                changelog_results= analyse_changelog(f['raw_url'])
                print (changelog_results)

            if 'code/API_definitions/' in f['filename']:
                print ('### OAS checks '+ f['filename'])
                OAS_results= analyse_OAS(f['raw_url'])
                print (OAS_results)
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
