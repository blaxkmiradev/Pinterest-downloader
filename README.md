# PinFrame Downloader (PyQt5)

A polished desktop app built with PyQt5 to download high-quality images and videos from Pinterest URLs.
Open-source release by **K-SEC**: https://rikixz.com

## Screenshot
![PinFrame Downloader UI](Screenshot.jpg)

## Features
- Modern multi-panel UI with gradient styling.
- Accepts multiple Pinterest links (one per line).
- Supports both pin URLs and profile URLs.
- Background worker thread keeps the UI responsive.
- Auto-detects high-quality media via Pinterest pin metadata.
- Supports image and video downloads.
- Profile mode crawls public profile pins using Pinterest bookmark pagination.
- Progress tracking, queue status table, and live image/video preview.
- Saves downloads into your chosen folder with safe unique filenames.

## Project Structure
```text
simple-project/
  run.py
  requirements.txt
  README.md
  app/
    __init__.py
    main.py
    constants.py
    resources/
      style.qss
    services/
      downloader.py
      pinterest_resolver.py
      profile_collector.py
    ui/
      main_window.py
    utils/
      media.py
      pinterest_urls.py
      paths.py
      validation.py
    workers/
      download_worker.py
```

## Setup
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run
```powershell
python run.py
```

## Usage
1. Paste Pinterest pin URLs and/or profile URLs in the left text box (one URL per line).
2. Choose your download folder.
3. Click `Download Media`.
4. Wait while the queue is prepared (profile links are expanded to pin links).
5. Check status in the queue table and click any successful row to preview.

## License
MIT (see `LICENSE`).

## Note
Only download content you have rights to use.
