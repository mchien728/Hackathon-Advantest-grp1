from flask import Flask, jsonify, request, render_template
from openai import OpenAI
import logging
import os
import json

from send_mail import send_dashboard_email

state_data = {}
last_error_type = None
user_email = None

def get_state():
    return state_data

def create_app():
    app = Flask(__name__)

    api_key = os.environ.get("OPENROUTER_API_KEY")

    client = None

    if api_key:
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key
        )

    @app.route("/healthz")
    def healthz():
        return "ok"

    @app.route("/api/state", methods=["GET", "POST"])
    def api_state():
        if request.method == "POST":
            try:
                global state_data, last_error_type, user_email
                state_data = request.get_json()
                if "label" in state_data:
                    label = state_data["label"]
                    if label != "Normal" and label != last_error_type:
                        if user_email:
                            send_dashboard_email(state_data, user_email)
                    last_error_type = label
                return state_data, 200
            except Exception as e:
                logging.exception("Failed to get dashboard state")
                return jsonify({"error": str(e)}), 500
        else:
            return state_data, 200

    @app.route("/api/email", methods=["GET", "POST"])
    def api_email():
        global user_email

        if request.method == "POST":
            data = request.get_json(silent=True) or {}
            user_email = str(data.get("email", "")).strip()

            return jsonify({
                "email": user_email
            }), 200

        return jsonify({
            "email": user_email or ""
        }), 200

    @app.route("/api/chat", methods=["POST"])
    def api_chat():
        try:
            if client is None:
                return jsonify({
                    "error": "OpenRouter API key is not configured."
                }), 500

            data = request.get_json(silent=True) or {}
            question = str(data.get("question", "")).strip()

            if not question:
                return jsonify({
                    "error": "Question is required."
                }), 400

            state = get_state()

            context = {
                "lot": state.get("lot"),
                "wafer": state.get("wafer"),
                "touchdown": state.get("touchdown"),
                "label": state.get("label"),
                "confidence": state.get("confidence"),
                "indicators": state.get("indicators"),
            }

            with open('prompt.txt', 'r', encoding='utf-8') as f:
                prompt = f.read()
                completion = client.chat.completions.create(
                    model="openrouter/free",
                    messages=[
                        {
                            "role": "system",
                            "content": prompt
                        },
                        {
                            "role": "user",
                            "content": f"""
    Current production data:

    {json.dumps(context, ensure_ascii=False)}

    Question:

    {question}
    """
                        }
                    ]
                )

            answer = completion.choices[0].message.content

            return jsonify({
                "answer": answer
            })

        except Exception as e:
            logging.exception("AI assistant request failed")

            return jsonify({
                "error": str(e)
            }), 500

    @app.route("/")
    def index():
        return render_template("index.html")

    return app


def start_dashboard(host="0.0.0.0", port=5000):
    app = create_app()
    app.run(
        host=host,
        port=port,
        use_reloader=False,
        threaded=True
    )

if __name__ == "__main__":
    start_dashboard()
