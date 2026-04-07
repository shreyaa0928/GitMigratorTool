if __name__ == "__main__":
    print("-" * 40)
    print("🚀 UNIVERSAL GIT MIGRATOR (CLI MODE)")
    print("-" * 40)
    
    source = input("Source Git URL (e.g. https://github.com/user/repo.git): ").strip()
    raw_target = input("Target Repo Path (e.g. user/target-repo): ").strip()
    
    # NEW: URL Parsing for Direct Fix
    target = raw_target
    if "://" in target: target = target.split("://")[-1]
    for domain in ["github.com/", "gitlab.com/", "bitbucket.org/"]:
        if domain in target: target = target.split(domain)[-1]
    if target.endswith(".git"): target = target[:-4]
    
    token = input("Target Provider Token: ").strip()
    provider = input("Target Provider (github/gitlab/bitbucket): ").strip().lower()

    if not all([source, target, token, provider]):
        print("❌ All fields are required!")
    else:
        # Resolve target URL based on provider
        if "gitlab" in provider:
            target_url = f"https://oauth2:{token}@gitlab.com/{target}.git"
        elif "github" in provider:
            target_url = f"https://x-access-token:{token}@github.com/{target}.git"
        elif "bitbucket" in provider:
            target_url = f"https://x-token-auth:{token}@bitbucket.org/{target}.git"
        else:
            print("❌ Unsupported provider. Using generic auth.")
            target_url = target
            
        direct_migrate(source, target, target_url)

def direct_migrate(source_url, target_name, target_url):
    import subprocess
    import os
    import tempfile
    import shutil
    from datetime import datetime

    print(f"\n[{datetime.now().isoformat()}] Starting migration...")
    temp_dir = tempfile.mkdtemp()
    sys_env = os.environ.copy()
    sys_env["GIT_TERMINAL_PROMPT"] = "0"
    sys_env["GIT_ASKPASS"] = "true"
    
    try:
        print(f"📦 Phase 1: Bare cloning {source_url}...")
        subprocess.run(["git", "clone", "--bare", source_url, temp_dir], check=True, env=sys_env)
        
        print(f"🚀 Phase 2: Force pushing to {target_name}...")
        subprocess.run(["git", "push", "--all", "--force", target_url], cwd=temp_dir, check=True, env=sys_env)
        subprocess.run(["git", "push", "--tags", "--force", target_url], cwd=temp_dir, check=True, env=sys_env)
        
        print("\n" + "=" * 40)
        print("🎉 SUCCESS! Repository migrated successfully.")
        print("=" * 40)
    except Exception as e:
        print(f"\n❌ FAILED: {str(e)}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
