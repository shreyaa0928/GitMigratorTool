import subprocess
import os
import tempfile
import shutil
from datetime import datetime

# USER: Please fill these values from your config or UI
SOURCE_URL = "https://github.com/shreyaa0928/portfolio.git" 
TARGET_REPO = "shreyaa0928/portfolio_clone"
GITLAB_TOKEN = "glpat-xxxxxxxxxxxxxxxx" # YOUR GITLAB TOKEN HERE

def direct_migrate():
    print(f"[{datetime.now().isoformat()}] Starting direct migration...")
    
    temp_dir = tempfile.mkdtemp()
    sys_env = os.environ.copy()
    sys_env["GIT_TERMINAL_PROMPT"] = "0"
    sys_env["GIT_ASKPASS"] = "true"
    
    try:
        # 1. Clone Source
        print(f"Phase 1: Cloning source {SOURCE_URL}...")
        subprocess.run(["git", "clone", "--bare", SOURCE_URL, temp_dir], check=True, env=sys_env)
        
        # 2. Push to GitLab
        # We assume the user is shreyaa0928
        target_url = f"https://oauth2:{GITLAB_TOKEN}@gitlab.com/{TARGET_REPO}.git"
        print(f"Phase 2: Pushing to {TARGET_REPO}...")
        
        subprocess.run(["git", "push", "--all", "--force", target_url], cwd=temp_dir, check=True, env=sys_env)
        subprocess.run(["git", "push", "--tags", "--force", target_url], cwd=temp_dir, check=True, env=sys_env)
        
        print("🎉 SUCCESS! Repo migrated directly.")
    except Exception as e:
        print(f"❌ FAILED: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    if "xxxx" in GITLAB_TOKEN:
        print("Please edit this file and put your actual GitLab Token in line 10!")
    else:
        direct_migrate()
