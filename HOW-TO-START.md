# How to start the CRM on this laptop

You only need the laptop app to **import or research new leads**.
The Chrome extension works without it if it's set to **"Online (works anywhere)"**.

## Start it

1. Open the `medbill-outreach` folder on the Desktop.
2. Click the address bar at the top of the folder window, type `powershell`, and press **Enter**.
   A blue/black window opens in this folder.
3. Paste this line and press **Enter**:

   ```
   powershell -ExecutionPolicy Bypass -File .\start.ps1
   ```

   (This runs the app once without changing any Windows security setting.)
4. Wait about 10–20 seconds until you see `Application startup complete`.
5. Open **http://localhost:8000** in Chrome and log in.

**Keep that window open.** Closing it turns the app off.

## Stop it

Click the PowerShell window and press **Ctrl + C**, or just close the window.

## If something goes wrong

- **"address already in use" / "error while attempting to bind"**: the app is already running.
  Just open http://localhost:8000.
- **The page doesn't load**: wait a few more seconds and refresh. If it still fails, close the
  PowerShell window and start again from step 2.
