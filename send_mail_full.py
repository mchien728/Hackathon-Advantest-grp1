import resend
import os


resend.api_key = "re_YUAJpFEd_JWtExe6zutj1iWp5gpDyu1bs"


def build_email_html(state):

    label = state.get("label", "Normal")
    touchdown = state.get("touchdown", "-")
    wafer = state.get("wafer", "-")
    confidence = state.get("confidence", 0)

    # 之後後端有溫度就直接換這裡
    temperature = state.get("temperature", "--")

    # 找被觸發的 anomaly
    triggered = [
        x for x in state.get("indicators", [])
        if x.get("triggered")
    ]

    # =========================
    # Wafer Map
    # =========================

    wafer_map = state.get("wafer_map", {})

    columns = wafer_map.get("columns", [])
    rows = wafer_map.get("rows", [])

    x_index = columns.index("x")
    y_index = columns.index("y")
    passed_index = columns.index("passed")
    suspect_index = columns.index("suspect")

    dies = {}

    for row in rows:

        x = row[x_index]
        y = row[y_index]

        passed = row[passed_index]
        suspect = row[suspect_index]

        if not passed:
            color = "#ef4444"     # Fail

        elif suspect:
            color = "#f59e0b"     # Suspect

        else:
            color = "#22c55e"     # Pass

        dies[(x, y)] = color


    # 你的 wafer layout
    wafer_layout = [
        (6,0), (9,4), (3,3), (3,5), (4,1),
        (5,2), (5,4), (8,5), (1,5), (6,3),
        (8,1), (4,5), (8,4), (11,4), (1,6),
        (4,2), (10,3), (0,3), (11,3), (8,6),
        (3,0), (6,7), (6,2), (5,8), (7,4),
        (6,6), (1,3), (9,1), (6,5), (7,6),
        (4,3), (8,7), (2,5), (10,5), (7,7),
        (4,8), (3,7), (7,8), (9,5), (0,4),
        (7,0), (8,0), (8,3), (9,6), (5,1),
        (2,7), (2,1), (2,2), (10,2), (6,4),
        (3,6), (5,3), (7,1), (3,2), (5,6),
        (4,0), (7,5), (9,2), (2,4), (2,3),
        (7,2), (2,6), (7,3), (1,4), (1,2),
        (4,4), (5,0), (6,8), (9,3), (10,4),
        (3,1), (10,6), (5,5), (3,4), (5,7),
        (6,1), (8,2), (4,6), (9,7), (4,7)
    ]

    layout_set = set(wafer_layout)

    wafer_html = ""

    for y in range(0, 9):

        wafer_html += "<tr>"

        for x in range(0, 12):

            if (x, y) not in layout_set:

                wafer_html += """
                <td width="20" height="20"></td>
                """

                continue

            color = dies.get(
                (x, y),
                "#e1e5eb"
            )

            wafer_html += f"""
            <td
                width="20"
                height="20"
                style="
                    background:{color};
                    border:2px solid white;
                    border-radius:4px;
                "
            ></td>
            """

        wafer_html += "</tr>"


    # =========================
    # Anomaly Detail
    # =========================

    alert_html = ""

    for item in triggered:

        detail = item.get("detail", {})

        alert_html += f"""
        <div style="
            margin-top:12px;
            padding:12px;
            background:white;
            border:1px solid #e5e7eb;
            border-radius:8px;
        ">

            <strong>
                {item.get("name", "-")}
            </strong>

            <div style="
                margin-top:6px;
                color:#6b7280;
                font-size:13px;
            ">
                Value:
                {item.get("value", "-")}
                &nbsp;&nbsp;

                Threshold:
                {item.get("threshold", "-")}
                <br>

                Direction:
                {detail.get("direction", "-")}
                &nbsp;&nbsp;

                Group:
                {detail.get("group", "-")}
            </div>

        </div>
        """


    if label.lower() == "normal":

        anomaly_background = "#f0fdf4"
        anomaly_color = "#166534"
        anomaly_title = "No anomalies detected"

    else:

        anomaly_background = "#fef2f2"
        anomaly_color = "#dc2626"
        anomaly_title = label


    # =========================
    # 完整 Email
    # =========================

    return f"""
    <html>

    <body style="
        margin:0;
        padding:30px;
        background:#f4f6f8;
        font-family:Arial,sans-serif;
        color:#1f2937;
    ">

        <div style="
            max-width:1000px;
            margin:auto;
        ">

            <h1>
                Advantest AI Production Monitor
            </h1>

            <p style="color:#6b7280;">
                Wafer {wafer}
                · Touchdown {touchdown}
            </p>


            <!-- =====================
                 Wafer + Temperature
                 ===================== -->

            <table
                width="100%"
                cellpadding="0"
                cellspacing="0"
                style="margin-top:20px;"
            >

                <tr>

                    <!-- Wafer Map -->

                    <td
                        width="50%"
                        valign="top"
                        style="
                            background:white;
                            padding:25px;
                            border-radius:12px;
                        "
                    >

                        <h2>
                            Wafer Map
                        </h2>

                        <table
                            cellpadding="0"
                            cellspacing="0"
                            align="center"
                        >

                            {wafer_html}

                        </table>


                        <div style="
                            margin-top:20px;
                            font-size:13px;
                        ">

                            🟩 Pass
                            &nbsp;

                            🟥 Fail
                            &nbsp;

                            🟧 Suspect
                            &nbsp;

                            ⬜ Not tested

                        </div>

                    </td>


                    <td width="20">
                    </td>


                    <!-- Temperature -->

                    <td
                        width="50%"
                        valign="top"
                        align="center"
                        style="
                            background:white;
                            padding:25px;
                            border-radius:12px;
                        "
                    >

                        <h2>
                            IC Temperature Prediction
                        </h2>

                        <div style="
                            font-size:48px;
                            font-weight:bold;
                            margin-top:70px;
                        ">

                            {temperature} °C

                        </div>

                        <div style="
                            margin-top:10px;
                            color:#6b7280;
                        ">

                            Current predicted temperature

                        </div>

                    </td>

                </tr>

            </table>


            <!-- =====================
                 Anomaly Report
                 ===================== -->

            <div style="
                background:white;
                padding:25px;
                border-radius:12px;
                margin-top:20px;
            ">

                <h2 style="margin-top:0;">
                    Anomaly Report
                </h2>

                <p style="
                    color:#6b7280;
                ">
                    AI analysis of the latest test results
                </p>


                <div style="
                    background:{anomaly_background};
                    padding:20px;
                    border-radius:10px;
                    margin-top:18px;
                ">

                    <div style="
                        font-size:20px;
                        font-weight:bold;
                        color:{anomaly_color};
                    ">

                        {anomaly_title}

                    </div>


                    <p>
                        Wafer:
                        <strong>{wafer}</strong>

                        <br>

                        Touchdown:
                        <strong>{touchdown}</strong>

                        <br>

                        Confidence:
                        <strong>
                            {confidence:.1%}
                        </strong>
                    </p>


                    {alert_html}

                </div>

            </div>

        </div>

    </body>

    </html>
    """


def send_dashboard_email(state):

    html = build_email_html(state)

    r = resend.Emails.send({

        "from":
            "Advantest Monitor <onboarding@resend.dev>",

        "to":
            ["zhixuan900422@gmail.com"],

        "subject":
            f"[Advantest Alert] "
            f"{state.get('wafer')} - "
            f"{state.get('label')}",

        "html":
            html
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

    with open(
        "test_email.html",
        "w",
        encoding="utf-8"
    ) as f:
        f.write(html)

    print("✅ test_email.html 已建立")


    # =========================
    # 再真的寄信
    # =========================

    send_dashboard_email(test_state)