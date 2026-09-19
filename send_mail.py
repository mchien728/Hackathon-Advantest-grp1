import resend

resend.api_key = "re_YUAJpFEd_JWtExe6zutj1iWp5gpDyu1bs"

r = resend.Emails.send({
  "from": "onboarding@resend.dev",
  "to": "zhixuan900422@gmail.com",
  "subject": "Hello World",
  "html": "<p>Congrats on sending your <strong>first email</strong>!</p>"
})