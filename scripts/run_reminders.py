"""One local in-system reminder sweep, using private PETOPS_DATABASE_URL."""
from app.notifications import reminder_job

if __name__=='__main__':
    print('In-system reminders created:',reminder_job())
