# Campus OD localhost demonstration

This guide uses fictional accounts and files. The demo command uses SQLite, its own JWT signing key, and private file storage under `.campus-od-demo` in the current Windows user's home directory. The ordinary FastAPI launcher uses the configured PostgreSQL connection, which may point to live Supabase. For this demo, use `app.local_demo serve` from the commands below.

Use Chrome or Edge at `http://localhost:5173`. The frontend proxies `/api/v1` to FastAPI at `127.0.0.1:8001`. Keep the browser hostname and port as shown so the refresh cookie, Origin checks, and location permission work together.

## 1. Initialize and bootstrap once

Use PowerShell with the existing backend virtual environment and a current Node.js installation. For a fresh demo directory:

```powershell
Set-Location 'D:\CAMPUS OD\backend'
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m app.local_demo init
.\venv\Scripts\python.exe -m app.local_demo bootstrap-admin --confirm-demo-admin
```

`init` creates the SQLite file, private keys, fictional department, academic year, and class. It refuses to overwrite an existing directory. Bootstrap is an explicit operator action in an interactive terminal. Enter and confirm a unique demo password of at least 15 characters at the hidden prompts. The administrator login is `demo.admin@example.com`. Bootstrap refuses to create a second administrator.

To use a separate demo directory, pass `--directory 'D:\path\to\private-demo'` **before** the subcommand on every backend command in this guide, including `init`, `bootstrap-admin`, `serve`, `copy-invitation`, and `prepare-od`. Keep that directory private and outside Git.

## 2. Start both servers

**Backend terminal**

```powershell
Set-Location 'D:\CAMPUS OD\backend'
.\venv\Scripts\python.exe -m app.local_demo serve
```

**Frontend terminal**

```powershell
Set-Location 'D:\CAMPUS OD\frontend'
npm ci
npm run dev
```

Run `npm ci` on first setup or after dependency changes. Open `http://localhost:5173`. In a third terminal, confirm the backend is connected to **SQLite** before entering any demo credentials:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8001/api/v1/health/db' |
    Select-Object connected, database
```

The expected values are `connected = True` and `database = SQLite`. The dev server needs port 5173 and the demo backend needs port 8001.

## 3. Provision and activate the fictional accounts

1. Sign in as the demo administrator. Open **User Management** and create any missing Student, Tutor, and Head of Department accounts from the approved roster. The HOD account reserves the Demo Department assignment during provisioning. Note each invitation ID.
2. Sign out of the administrator portal. In a local operator terminal, copy one invitation code at a time using its ID:

   ```powershell
   Set-Location 'D:\CAMPUS OD\backend'
   $invitationId = Read-Host 'Invitation ID'
   .\venv\Scripts\python.exe -m app.local_demo copy-invitation $invitationId
   ```

3. Open **Activate an invited account** on the sign-in screen. Paste the code into the invitation field and set a demo password. Repeat for each new account. The logins are `demo.student@example.com`, `demo.tutor@example.com`, and `demo.hod@example.com`. Keep the codes and passwords private, disable clipboard history for the demonstration, and clear the clipboard after pasting.
4. After the tutor is activated, run:

   ```powershell
   Set-Location 'D:\CAMPUS OD\backend'
   .\venv\Scripts\python.exe -m app.local_demo prepare-od
   ```

`prepare-od` creates missing local workflow tables when upgrading an older demo and assigns the active demo tutor to the demo class. It preserves existing records and refuses to replace a different or inactive mapping. Both servers can remain running during this step. For intentional mapping changes, use the administrator’s **Academic Assignments** page.

## 4. Present the workflow

Use separate browser profiles for the administrator, student, tutor, and HOD if you want to switch roles without repeated sign-ins. Tabs in a single profile share one refresh cookie. The administrator overview shows labeled sample figures. Use **User Management** and **Academic Assignments** for the current demo records.

1. Sign in as the student and submit an OD application with at least two event dates, a fictional signed form, and optional supporting documents. The server assigns the current class tutor.
2. Sign in as the assigned tutor, open the application, download the original form, and request a correction with remarks. As the student, correct and resubmit it. As the tutor, preapprove the corrected application.
3. As the student, open the preapproved application and select **Capture location** on each event day. Grant location permission and attach a fictional venue image (PNG or JPEG) and organizer proof (PDF, PNG, or JPEG). Use a browser location override for fictional presentation coordinates. Permission denial leaves submission unavailable until a capture succeeds.
4. As the tutor, download the evidence, inspect GPS and timestamps, and review each day. Request an evidence correction to demonstrate a new attempt and retained history. After the student resubmits, verify the last outstanding day. The tutor and student will see **Awaiting HOD review**.
5. Sign in as the HOD, open **Pending Requests**, and review the original form, tutor remarks, and GPS and files for both days. Select **Record decision**, then **Approve and finalize OD**. The application moves to **Decision History** and the student sees **OD finalized** with the HOD’s name, timestamp, and any remarks.
6. To demonstrate an HOD correction, choose **Request correction** and provide remarks on a different request. The student resubmits a revised description or supporting documents. The tutor can reopen individual evidence days and then forward the correction after every day is verified.
7. As the administrator, open **Academic Assignments** to inspect class-tutor and department HOD mappings. Changing a class-tutor mapping applies to future applications. Ending or replacing an HOD assignment preserves its history and revokes the affected HOD sessions.

The default file size limit is 5 MiB per upload. Use fictional files without student signatures, personal data, or real location metadata.

## Existing demo directories

Starting the updated backend and opening the app applies the additive SQLite schema upgrade. Keep using the existing directory and credentials. The upgrade backfills the application department from each student’s current department, creates the HOD assignment table, and preserves existing status history and uploaded files. Previously finalized records retain their existing status and actor. Provision the fictional HOD through **User Management**.

## Refresh, restart, and limits

- Refresh the student application page to check that the browser restores the session and shows the finalized record. To repeat after a restart, stop both servers with Ctrl+C and run the same startup commands with the same demo directory. Existing accounts, records, files, and signing keys persist there. Session restoration depends on the refresh cookie and its expiry. Logout clears the browser session.
- GPS and photo watermarks are supporting evidence that can be spoofed. The demo applies no distance tolerance or attendance time window. The current schema has no expected venue coordinates for computing a distance.
- The roster and invitation delivery are local demo features. Live Supabase writes and deployed PostgreSQL behavior are outside this verification.

For frontend checks, run `npm run build` and `node --test tests/*.test.js` from `frontend`. From `backend`, run `.\venv\Scripts\python.exe -m unittest discover -q`. Backend demo tests use temporary SQLite databases and fictional accounts. [HOD approval guide](HOD_APPROVAL.md)
