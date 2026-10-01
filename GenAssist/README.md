# GenAssist Web

This bundle connects the supplied HTML frontend to a Python backend.

## Run

1. Open a terminal in this folder.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Start the application:

   ```powershell
   python app.py
   ```

4. Open `http://127.0.0.1:8000`.

Speech generation works immediately and requires internet access.

## Enable DreamTalk video

Clone DreamTalk and add its official academic checkpoint. Then set the folder before
starting the application:

```powershell
$env:DREAMTALK_DIR = "C:\path\to\dreamtalk"
python app.py
```

The backend expects the standard DreamTalk sample style and pose files. The official
checkpoint is not publicly downloadable and must be requested from the DreamTalk
authors.

To select a default portrait:

```powershell
$env:GENASSIST_DEFAULT_PORTRAIT = "C:\path\to\portrait.png"
python app.py
```

Users can also upload a portrait from the frontend.
