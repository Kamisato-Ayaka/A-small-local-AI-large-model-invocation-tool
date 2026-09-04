import sys, time
from modelscope import snapshot_download
ok = False
for attempt in range(3):
    try:
        snapshot_download(sys.argv[1], local_dir=sys.argv[2])
        ok = True
        break
    except Exception as e:
        print(f'DOWNLOAD_RETRY {attempt + 1}: {e}', flush=True)
        time.sleep(3)
print('DOWNLOAD_DONE' if ok else 'DOWNLOAD_FAILED')
sys.exit(0 if ok else 1)
