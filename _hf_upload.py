import sys, time
from huggingface_hub import HfApi

REPO_ID = "Kami0867/qwen2.5-3b-personalized-email-lora"
FOLDER = r"C:\Users\Kmai1\Documents\GitHub\Email-writer-2.5-3B\checkpoints\qwen-email-sft-best"

api = HfApi()

print("Creating/ensuring repo:", REPO_ID, flush=True)
url = api.create_repo(repo_id=REPO_ID, repo_type="model", exist_ok=True, private=False)
print("Repo URL:", url, flush=True)

t0 = time.time()
print("Uploading folder:", FOLDER, flush=True)
res = api.upload_folder(
    repo_id=REPO_ID,
    folder_path=FOLDER,
    repo_type="model",
    commit_message="Archive Qwen2.5-3B personalized email SFT LoRA adapter (r=16, 3 epochs, train_loss=0.556)",
)
print("Upload done in %.1fs" % (time.time() - t0), flush=True)
print("Commit:", getattr(res, "commit_url", None), getattr(res, "oid", None), flush=True)
