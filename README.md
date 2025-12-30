# QuizApp

A Flask-based web application for creating and managing quizzes with admin and user roles. Features include quiz creation, user management, email notifications, and result tracking with LaTeX math equation support.

## Features

- **Admin Dashboard**: Create and manage quizzes, view results, and manage users
- **User Portal**: Take quizzes with attempt tracking and instant feedback
- **LaTeX Support**: Render mathematical equations using KaTeX
- **Email Notifications**: Automatic email delivery of quiz results to users
- **Session Management**: Secure session handling with configurable cookies
- **Attempt Tracking**: Configurable maximum attempts per quiz
- **Result Analytics**: View detailed quiz results and user performance

## Technology Stack

- **Backend**: Flask 3.0.0
- **Database**: SQLAlchemy 2.0.23 with SQLite
- **Session Management**: Flask-Session 0.5.0
- **Email**: Custom SMTP mailer implementation
- **Math Rendering**: KaTeX (frontend)
- **Production Server**: Gunicorn 21.2.0

## Project Structure

```
QuizApp/
├── app/
│   ├── blueprints/          # Flask blueprints
│   │   ├── admin.py         # Admin routes
│   │   ├── auth.py          # Authentication routes
│   │   └── user.py          # User routes
│   ├── data/
│   │   └── questions/       # Quiz JSON files
│   ├── static/              # Static assets (CSS, JS, images)
│   ├── templates/           # Jinja2 templates
│   ├── __init__.py          # Application factory
│   ├── config.py            # Configuration settings
│   ├── database.py          # Database setup
│   ├── mail.py              # Email functionality
│   ├── models.py            # SQLAlchemy models
│   └── utils.py             # Utility functions
├── instance/                # Instance-specific files (database)
├── venv/                    # Virtual environment
├── .env                     # Environment variables (not in git)
├── .env.example             # Example environment variables
├── init_db.py               # Database initialization script
├── requirements.txt         # Python dependencies
└── run.py                   # Application entry point
```

## Installation

### Prerequisites

- Python 3.8+
- pip
- Virtual environment (recommended)

### Setup

1. Clone the repository:
```bash
git clone https://github.com/zaidkx7/QuizApp.git
cd QuizApp
```

2. Create and activate a virtual environment:
```bash
# Windows
python -m venv venv
venv\Scripts\activate

# macOS/Linux
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env with your configuration
```

5. Set up the environment variables in `.env`:
```env
SECRET_KEY=your-secret-key-here
EMAIL_USERNAME=your-email@example.com
EMAIL_PASSWORD=your-email-password
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_FROM=noreply@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=secure-admin-password
ADMIN_EMAIL=admin@example.com
BASE_URL=http://localhost:8080
```

6. Initialize the database:
```bash
python init_db.py
```

7. Run the application:
```bash
# Development
python run.py

# Production (using Gunicorn)
gunicorn -w 4 -b 0.0.0.0:8080 run:app
```

The application will be available at `http://localhost:8080`

## Database Models

### User
- Stores user information (students and admins)
- Fields: id, username, user_id, password, email, role

### Quiz
- Stores quiz metadata
- Fields: id, title, filename, created_at

### Result
- Stores quiz submission results
- Fields: id, user_id, quiz_id, score, submitted_at, answers, email_sent

### Settings
- Application-wide settings
- Fields: id, max_attempts, smtp_enabled

## Usage

### Admin Access

1. Navigate to `/admin/login`
2. Login with admin credentials from `.env`
3. Access features:
   - Create/manage quizzes
   - View all results
   - Manage users
   - Configure settings (max attempts, SMTP)

### User Access

1. Navigate to `/user/register`
2. Login with credentials provided by admin
3. Features:
   - Take available quizzes
   - View attempt history
   - Receive results via email

### Creating Quizzes

Quizzes are stored as JSON files in `app/data/questions/`. Format:
```json
{
    "title": "Quiz - Sample",
    "true_false": [
      {
        "question": "The Earth is flat.",
        "answer": false
      },
      {
        "question": "Water boils at 100 degrees Celsius at sea level.",
        "answer": true
      },
      {
        "question": "JavaScript and Java are the same programming language.",
        "answer": false
      },
      {
        "question": "The Great Wall of China is visible from space with the naked eye.",
        "answer": false
      },
      {
        "question": "SQL stands for Structured Query Language.",
        "answer": true
      },
      {
        "question": "There are 12 months in a year.",
        "answer": true
      },
      {
        "question": "Gold is the most abundant metal in Earth's crust.",
        "answer": false
      }
    ],
    "mcqs": [
      {
        "question": "What is the largest planet in our solar system?",
        "options": ["Earth", "Mars", "Jupiter", "Saturn"],
        "answer": "Jupiter"
      },
      {
        "question": "Which programming language is known as the 'language of the web'?",
        "options": ["Python", "JavaScript", "C++", "Ruby"],
        "answer": "JavaScript"
      }
    ]
  }
```

## Configuration

### Email Settings

Configure SMTP settings in `.env` for email notifications:
- Gmail: Use App Passwords (not regular password)
- Other providers: Check their SMTP documentation

### Security Settings

- `SECRET_KEY`: Used for session encryption
- `SESSION_COOKIE_SECURE`: Set to True in production with HTTPS
- `SESSION_COOKIE_HTTPONLY`: Prevents XSS attacks
- `SESSION_COOKIE_SAMESITE`: CSRF protection

## Development

### Database Migrations

To recreate the database:
```bash
python init_db.py
```

This will create:
- users table
- quizzes table
- results table
- settings table

### Running Tests

(Add test instructions when tests are implemented)

## Production Deployment

1. Set `BASE_URL` to your production domain in `.env`
2. Use a production-grade database (PostgreSQL recommended)
3. Enable HTTPS and set `SESSION_COOKIE_SECURE=True`
4. Use environment variables for sensitive data
5. Run with Gunicorn or another WSGI server:
```bash
gunicorn -w 4 -b 0.0.0.0:8080 run:app
```

## Recent Updates

- Fixed CRITICAL bug in quiz submission (commit d383613)
- Changed email purpose functionality (commit db6b253)
- Implemented KaTeX for LaTeX math equation formatting (commit 2eb6300)
- Added toast notification alternative (commit f099ed5)
- Added secret_key and session management (commit 64697ae)
