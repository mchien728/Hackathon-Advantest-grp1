import resend
import os
from jinja2 import Environment, FileSystemLoader

resend.api_key = "re_YUAJpFEd_JWtExe6zutj1iWp5gpDyu1bs"

def get_wafer_grid(state):
    wafer_map = state.get("wafer_map", {})
    columns = wafer_map.get("columns", [])
    rows = wafer_map.get("rows", [])

    dies = {}
    if "x" in columns and "y" in columns and "passed" in columns and "suspect" in columns:
        x_idx = columns.index("x")
        y_idx = columns.index("y")
        passed_idx = columns.index("passed")
        suspect_idx = columns.index("suspect")

        for row in rows:
            x, y = row[x_idx], row[y_idx]
            passed, suspect = row[passed_idx], row[suspect_idx]

            if not passed:
                dies[(x, y)] = "#ef4444"  # Fail (Red)
            elif suspect:
                dies[(x, y)] = "#f59e0b"  # Suspect (Orange)
            else:
                dies[(x, y)] = "#22c55e"  # Pass (Green)

    wafer_layout = [
        (6,0), (9,4), (3,3), (3,5), (4,1), (5,2), (5,4), (8,5), (1,5), (6,3),
        (8,1), (4,5), (8,4), (11,4), (1,6), (4,2), (10,3), (0,3), (11,3), (8,6),
        (3,0), (6,7), (6,2), (5,8), (7,4), (6,6), (1,3), (9,1), (6,5), (7,6),
        (4,3), (8,7), (2,5), (10,5), (7,7), (4,8), (3,7), (7,8), (9,5), (0,4),
        (7,0), (8,0), (8,3), (9,6), (5,1), (2,7), (2,1), (2,2), (10,2), (6,4),
        (3,6), (5,3), (7,1), (3,2), (5,6), (4,0), (7,5), (9,2), (2,4), (2,3),
        (7,2), (2,6), (7,3), (1,4), (1,2), (4,4), (5,0), (6,8), (9,3), (10,4),
        (3,1), (10,6), (5,5), (3,4), (5,7), (6,1), (8,2), (4,6), (9,7), (4,7)
    ]
    layout_set = set(wafer_layout)

    # 9(y) x 12(x)
    grid = []
    for y in range(9):
        row_colors = []
        for x in range(12):
            if (x, y) not in layout_set:
                row_colors.append(None)
            else:
                row_colors.append(dies.get((x, y), "#e5e7eb"))
        grid.append(row_colors)

    return grid

def build_email_html(state):
    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates')))
    template = env.get_template('email_template.html')

    triggered = [x for x in state.get("indicators", []) if x.get("triggered")]

    wafer_grid = get_wafer_grid(state)

    return template.render(
        label=state.get("label", "Normal"),
        touchdown=state.get("touchdown", "-"),
        wafer=state.get("wafer", "-"),
        confidence=state.get("confidence", 0),
        temperature=state.get("temperature", "--"),
        triggered=triggered,
        wafer_grid=wafer_grid
    )

def send_dashboard_email(state):
    html = build_email_html(state)

    r = resend.Emails.send({
        "from": "Advantest Monitor <onboarding@resend.dev>",
        "to": ["zhixuan900422@gmail.com"],
        "subject": f"[Advantest Alert] {state.get('wafer')} - {state.get('label')}",
        "html": html
    })

    print("Email sent:", r)

if __name__ == "__main__":

    # =========================
    # 假的 Dashboard state
    # =========================
    test_state = {
        "lot": "LOT001",
        "wafer": "W14",
        "touchdown": 20,

        "label": "Mean Trend Up",
        "confidence": 0.786,

        # 暫時測試溫度
        "temperature": 72.5,

        "indicators": [
            {
                "id": 2,
                "key": "mean_trend",
                "name": "Mean Trend",
                "value": 110,
                "threshold": 30,
                "triggered": True,

                "detail": {
                    "direction": "up",
                    "group": "Main.subflow2",
                    "onset_td": 3
                }
            },

            {
                "id": 3,
                "key": "stdev_up",
                "name": "Stdev Trend",
                "value": 0,
                "threshold": 30,
                "triggered": False,

                "detail": {
                    "direction": "-",
                    "group": "Main.subflow2"
                }
            }
        ],

        "wafer_map": {

            "columns": [
                "td",
                "site",
                "x",
                "y",
                "sbin",
                "passed",
                "suspect"
            ],

            "rows": [

                [1, 1, 6, 0, 1, True, False],
                [1, 2, 9, 4, 1, True, False],
                [1, 3, 3, 3, 1, True, False],
                [1, 4, 3, 5, 1, True, False],

                [2, 1, 4, 1, 1, True, False],
                [2, 2, 5, 2, 1, True, False],

                # Suspect
                [2, 3, 5, 4, 1, True, True],

                [2, 4, 8, 5, 1, True, False],

                [3, 1, 1, 5, 1, True, False],

                # Fail
                [3, 2, 6, 3, 2, False, False],

                [3, 3, 8, 1, 1, True, False],
                [3, 4, 4, 5, 1, True, False]
            ],

            "extent": {
                "x": [0, 11],
                "y": [0, 8]
            }
        }
    }

    # =========================
    # 先輸出 HTML 看看
    # =========================

    html = build_email_html(test_state)
    with open("test_email.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✅ test_email.html 已建立")

    # =========================
    # 再真的寄信
    # =========================

    send_dashboard_email(test_state)
