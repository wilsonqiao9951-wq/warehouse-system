"""Run on loopback only after configuring a trusted provider. Disabled by default."""
import os
from app.integrations.whatsapp import create_app
app=create_app(enabled=os.environ.get('WHATSAPP_ADAPTER_ENABLED')=='true',signing_secret=os.environ.get('WHATSAPP_ADAPTER_SIGNING_SECRET',''),provider_id=os.environ.get('WHATSAPP_ADAPTER_PROVIDER','simulation'),recipient_id=os.environ.get('WHATSAPP_ADAPTER_RECIPIENT','simulation-line'),state_path=os.environ.get('WHATSAPP_ADAPTER_STATE','artifacts/whatsapp/channel.sqlite3'))
