from flask import Flask, render_template, request, session
import pandas as pd
import os
import base64
import uuid
import mimetypes

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage

from werkzeug.utils import secure_filename

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


app = Flask(__name__)

# Required for Flask session
app.secret_key = "gmail-excel-automation-secret-key"

UPLOAD_FOLDER = "uploads"
ATTACHMENT_FOLDER = os.path.join(UPLOAD_FOLDER, "attachments")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["ATTACHMENT_FOLDER"] = ATTACHMENT_FOLDER

# Create folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ATTACHMENT_FOLDER, exist_ok=True)

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


# ---------------------------------------------------
# Gmail connection
# ---------------------------------------------------

def get_gmail_service():

    creds = Credentials.from_authorized_user_file(
        "token.json",
        SCOPES
    )

    return build(
        "gmail",
        "v1",
        credentials=creds
    )


# ---------------------------------------------------
# Home
# ---------------------------------------------------

@app.route("/")
def home():

    recipients = []

    if "excel_path" in session:

        filepath = session["excel_path"]

        if os.path.exists(filepath):

            df = pd.read_excel(filepath)

            for _, row in df.iterrows():

                recipients.append({
                    "name": str(row["Name"]),
                    "email": str(row["Email"])
                })

    return render_template(
        "index.html",
        recipients=recipients
    )


# ---------------------------------------------------
# Upload Excel
# ---------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload_file():

    file = request.files.get("excel")

    if not file or file.filename == "":
        return "No Excel file selected."

    filename = secure_filename(file.filename)

    filepath = os.path.join(
        app.config["UPLOAD_FOLDER"],
        filename
    )

    file.save(filepath)

    # Remember which Excel file we're using
    session["excel_path"] = filepath

    # Read Excel
    df = pd.read_excel(filepath)

    recipients = []

    for _, row in df.iterrows():

        recipients.append({
            "name": str(row["Name"]),
            "email": str(row["Email"])
        })

    return render_template(
        "index.html",
        recipients=recipients
    )


# ---------------------------------------------------
# Preview email + upload attachments
# ---------------------------------------------------

@app.route("/preview", methods=["POST"])
def preview_email():

    subject = request.form.get("subject", "")
    message = request.form.get("message", "")

    excel_path = session.get("excel_path")

    if not excel_path or not os.path.exists(excel_path):
        return "Please upload an Excel file first."

    # -----------------------------------------------
    # Save attachments
    # -----------------------------------------------

    uploaded_files = request.files.getlist("attachments")

    attachment_names = []

    for file in uploaded_files:

        if file and file.filename:

            original_name = secure_filename(file.filename)

            # Create unique filename
            unique_name = (
                str(uuid.uuid4())
                + "_"
                + original_name
            )

            filepath = os.path.join(
                app.config["ATTACHMENT_FOLDER"],
                unique_name
            )

            file.save(filepath)

            attachment_names.append({
                "name": original_name,
                "filename": unique_name
            })

    # -----------------------------------------------
    # Read Excel
    # -----------------------------------------------

    df = pd.read_excel(excel_path)

    recipients = []

    for _, row in df.iterrows():

        name = str(row["Name"])
        email = str(row["Email"])

        personalized_message = message.replace(
            "{{name}}",
            name
        )

        recipients.append({
            "name": name,
            "email": email,
            "message": personalized_message
        })

    return render_template(
        "index.html",
        recipients=recipients,
        subject=subject,
        message=message,
        preview=True,
        attachments=attachment_names
    )


# ---------------------------------------------------
# Send emails
# ---------------------------------------------------

@app.route("/send", methods=["POST"])
def send_emails():

    subject = request.form.get("subject", "")
    message = request.form.get("message", "")

    excel_path = session.get("excel_path")

    if not excel_path or not os.path.exists(excel_path):
        return "Please upload an Excel file first."

    # Get attachment filenames
    attachment_filenames = request.form.getlist(
        "attachment_files"
    )

    # Read Excel
    df = pd.read_excel(excel_path)

    # Gmail
    gmail = get_gmail_service()

    sent_count = 0

    for _, row in df.iterrows():

        name = str(row["Name"])
        email = str(row["Email"])

        personalized_message = message.replace(
            "{{name}}",
            name
        )

        # -------------------------------------------
        # Create email
        # -------------------------------------------

        mail = MIMEMultipart()

        mail["to"] = email
        mail["subject"] = subject

        # Add email text
        mail.attach(
            MIMEText(
                personalized_message,
                "plain",
                "utf-8"
            )
        )

        # -------------------------------------------
        # Add attachments
        # -------------------------------------------

        for filename in attachment_filenames:

            filepath = os.path.join(
                app.config["ATTACHMENT_FOLDER"],
                filename
            )

            if not os.path.exists(filepath):
                continue

            mime_type, _ = mimetypes.guess_type(filepath)

            if mime_type is None:
                mime_type = "application/octet-stream"

            main_type, sub_type = mime_type.split(
                "/",
                1
            )

            with open(filepath, "rb") as f:

                file_data = f.read()

            if main_type == "image":

                attachment = MIMEImage(
                    file_data,
                    _subtype=sub_type
                )

            else:

                attachment = MIMEApplication(
                    file_data,
                    _subtype=sub_type
                )

            attachment.add_header(
                "Content-Disposition",
                "attachment",
                filename=os.path.basename(
                    filepath
                )
            )

            mail.attach(attachment)

        # -------------------------------------------
        # Encode email
        # -------------------------------------------

        encoded_message = base64.urlsafe_b64encode(
            mail.as_bytes()
        ).decode()

        # -------------------------------------------
        # Send
        # -------------------------------------------

        gmail.users().messages().send(
            userId="me",
            body={
                "raw": encoded_message
            }
        ).execute()

        sent_count += 1

    return render_template(
        "index.html",
        recipients=[],
        sent=True,
        sent_count=sent_count
    )


# ---------------------------------------------------
# Run Flask
# ---------------------------------------------------

if __name__ == "__main__":
    app.run(debug=True)