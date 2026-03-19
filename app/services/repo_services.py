import os
from git import Repo, GitCommandError
from app.core.model_loader import model
REPO_DIR = "repos"

def clone_repository(repo_url):
    try:
        repo_name = repo_url.split("/")[-1].replace(".git", "")
        clone_path = os.path.join(REPO_DIR, repo_name)

        # create repos folder if not exists
        os.makedirs(REPO_DIR, exist_ok=True)

        # if already cloned
        if os.path.exists(clone_path):
            print(f"✅ Repo already exists: {clone_path}")
            return clone_path

        print(f"⬇️ Cloning {repo_url} ...")

        Repo.clone_from(repo_url, clone_path)

        print("✅ Clone successful")

        return clone_path

    except GitCommandError as e:
        print(f"❌ Git clone failed: {e}")
        return None

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return None