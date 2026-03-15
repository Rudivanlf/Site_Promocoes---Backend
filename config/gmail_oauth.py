import os
import base64
import json
from email.mime.text import MIMEText
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from django.conf import settings

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_gmail_service():
    creds = None
    
    # Suporte para ambientes de produção (Render/Docker) via variáveis de ambiente/settings
    token_json = getattr(settings, 'GOOGLE_TOKEN_JSON', None) or os.environ.get("GOOGLE_TOKEN_JSON")
    client_secret_json = getattr(settings, 'GOOGLE_CLIENT_SECRET_JSON', None) or os.environ.get("GOOGLE_CLIENT_SECRET_JSON")

    if token_json:
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)
    elif os.path.exists(settings.GOOGLE_TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(settings.GOOGLE_TOKEN_FILE, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if client_secret_json:
                client_config = json.loads(client_secret_json)
                flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    settings.GOOGLE_CLIENT_SECRET_FILE, SCOPES)
            
            creds = flow.run_local_server(port=0)
        
        # Salva o token localmente apenas se não estivermos em produção
        if not token_json:
            with open(settings.GOOGLE_TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
    
    return build('gmail', 'v1', credentials=creds)

def send_email_oauth(to_email, subject, message_text, from_email=None):
    try:
        service = get_gmail_service()
        
        if not from_email:
            from_email = settings.EMAIL_USER
        
        message = MIMEText(message_text)
        message['to'] = to_email
        message['from'] = from_email
        message['subject'] = subject
        
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
        
        response = service.users().messages().send(
            userId='me',
            body={'raw': raw_message}
        ).execute()

        print(f'Gmail API send response: {response}')

        return response
    except Exception as e:
        print(f'Erro ao enviar email: {e}')
        raise e