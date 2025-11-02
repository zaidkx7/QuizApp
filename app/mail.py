import smtplib

from app.config import Config
from flask import render_template

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class SMTPMailer:
    """Reusable SMTP client for sending HTML + text emails."""

    def __init__(self):
        # Use configuration from Config class
        self.username = Config.EMAIL_USERNAME
        self.password = Config.EMAIL_PASSWORD
        self.host = Config.EMAIL_HOST
        self.port = Config.EMAIL_PORT
        self.sender = Config.EMAIL_FROM
        self.base_url = Config.BASE_URL

    def create_message(self, to_email: str, subject: str, text: str, html: str) -> MIMEMultipart:
        """Create a multipart email message."""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.sender
        msg["To"] = to_email

        msg.attach(MIMEText(text, "plain"))
        msg.attach(MIMEText(html, "html"))
        return msg

    def send(self, to_email: str, subject: str, text: str, html: str):
        """Send an email via SMTP."""
        message = self.create_message(to_email, subject, text, html)

        try:
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.sender, to_email, message.as_string())
            print(f"✅ Email successfully sent to {to_email}")
            return True
        except Exception as e:
            print(f"❌ Failed to send email to {to_email}: {e}")
            return False

    def send_template(self, to_email: str, subject: str, template_name: str, context: dict):
        """Send an email using Flask templates.

        Args:
            to_email: Recipient email address
            subject: Email subject line
            template_name: Name of template (without extension), e.g., 'quiz_result'
            context: Dictionary of variables to pass to the template

        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Add base_url to context if not already present
            if 'base_url' not in context:
                context['base_url'] = self.base_url

            # Render HTML template
            html = render_template(f'emails/{template_name}.html', **context)

            # Render plain text template
            text = render_template(f'emails/{template_name}.txt', **context)

            # Send email
            return self.send(to_email, subject, text, html)
        except Exception as e:
            print(f"❌ Failed to render or send template email: {e}")
            return False


if __name__ == "__main__":
    # Example usage
    mailer = SMTPMailer()

    receiver = "zaidkx37@gmail.com"
    subject = "Your Quiz Results"
    text_content = """\
    Hello Student,

    Congratulations on completing your quiz!

    Your Score: 8/10
    Quiz Title: Python Basics Quiz

    Keep learning and improving!

    Regards,
    Quiz Team
    """

    html_content = """\
    <html>
      <body>
        <h2>Your Quiz Results</h2>
        <p>Congratulations on completing your quiz!</p>
        <p><b>Your Score:</b> 8/10</p>
        <p><b>Quiz Title:</b> Python Basics Quiz</p>
        <p>Keep learning and improving! 🎉</p>
        <br>
        <p>Regards,<br><b>Quiz Team</b></p>
      </body>
    </html>
    """

    mailer.send(receiver, subject, text_content, html_content)
