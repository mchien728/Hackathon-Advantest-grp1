let hoveredTD = null;
let selectedTD = null;

let hoveredSite = null;
let selectedSite = null;

const waferLayout = [
    [3,0], [4,0], [5,0], [6,0], [7,0], [8,0],

    [2,1], [3,1], [4,1], [5,1],
    [6,1], [7,1], [8,1], [9,1],

    [1,2], [2,2], [3,2], [4,2], [5,2],
    [6,2], [7,2], [8,2], [9,2], [10,2],

    [0,3], [1,3], [2,3], [3,3], [4,3], [5,3],
    [6,3], [7,3], [8,3], [9,3], [10,3], [11,3],

    [0,4], [1,4], [2,4], [3,4], [4,4], [5,4],
    [6,4], [7,4], [8,4], [9,4], [10,4], [11,4],

    [1,5], [2,5], [3,5], [4,5], [5,5],
    [6,5], [7,5], [8,5], [9,5], [10,5],

    [1,6], [2,6], [3,6], [4,6], [5,6],
    [6,6], [7,6], [8,6], [9,6], [10,6],

    [2,7], [3,7], [4,7], [5,7],
    [6,7], [7,7], [8,7], [9,7],

    [4,8], [5,8], [6,8], [7,8]
];

function updateWaferHighlight() {

    const activeTD =
        selectedTD !== null
            ? selectedTD
            : hoveredTD;

    const activeSite =
        selectedSite !== null
            ? selectedSite
            : hoveredSite;

    const dies =
        document.querySelectorAll('.wafer-die');

    dies.forEach(die => {

        const dieTD =
            die.dataset.td === ''
                ? null
                : Number(die.dataset.td);

        const dieSite =
            die.dataset.site === ''
                ? null
                : Number(die.dataset.site);

        // 沒有選 TD，也沒有選 Site
        if (
            activeTD === null &&
            activeSite === null
        ) {
            die.classList.remove('highlight');
            die.classList.remove('dimmed');
            return;
        }

        // 有 TD 條件時，要符合 TD
        const matchesTD =
            activeTD === null ||
            dieTD === activeTD;

        // 有 Site 條件時，要符合 Site
        const matchesSite =
            activeSite === null ||
            dieSite === activeSite;

        if (matchesTD && matchesSite) {
            die.classList.add('highlight');
            die.classList.remove('dimmed');
        } else {
            die.classList.remove('highlight');
            die.classList.add('dimmed');
        }
    });
}


function updateTimelineSelection() {

    document
        .querySelectorAll('.timeline-dot')
        .forEach(dot => {

            const td =
                Number(dot.dataset.td);

            dot.classList.toggle(
                'selected',
                selectedTD === td
            );
        });
}

function renderTimeline(waferMap, currentTD) {

    const track =
        document.getElementById('timeline-track');

    const currentLabel =
        document.getElementById('timeline-current');

    if (
        !waferMap ||
        !waferMap.rows ||
        waferMap.rows.length === 0
    ) {
        track.innerHTML =
            '<div class="timeline-empty">Waiting for test progress...</div>';

        currentLabel.textContent = '-';
        return;
    }

    const columns = waferMap.columns || [];
    const tdIndex = columns.indexOf('td');

    if (tdIndex === -1) {
        return;
    }

    const touchdowns = [
        ...new Set(
            waferMap.rows
                .map(row => row[tdIndex])
                .filter(td => td != null)
        )
    ].sort((a, b) => a - b);

    currentLabel.textContent =
        currentTD != null
            ? `Current: TD ${currentTD}`
            : '-';

    track.innerHTML = '';

    touchdowns.forEach((td, index) => {

        const item =
            document.createElement('div');

        item.className = 'timeline-item';

        const dot =
            document.createElement('div');

        dot.className = 'timeline-dot';
        dot.dataset.td = td;
        dot.textContent = td;

        dot.addEventListener('mouseenter', () => {

            if (selectedTD !== null) {
                return;
            }

            hoveredTD = td;

            updateWaferHighlight();
        });


        dot.addEventListener('mouseleave', () => {

            if (selectedTD !== null) {
                return;
            }

            hoveredTD = null;

            updateWaferHighlight();
        });

        dot.addEventListener('click', () => {

            hoveredTD = null;

            if (selectedTD === td) {
                selectedTD = null;
            } else {
                selectedTD = td;
            }

            updateTimelineSelection();
            updateWaferHighlight();
        });

        item.appendChild(dot);

        if (index < touchdowns.length - 1) {

            const line =
                document.createElement('div');

            line.className = 'timeline-line';

            item.appendChild(line);
        }

        track.appendChild(item);
    });
    updateTimelineSelection();
}

function updateSiteSelection() {

    document
        .querySelectorAll('.site-item')
        .forEach(item => {

            const site =
                Number(item.dataset.site);

            item.classList.toggle(
                'selected',
                selectedSite === site
            );
        });
}

function renderWaferMap(waferMap) {

    const container =
        document.getElementById('wafer-map');

    if (
        !waferMap ||
        !waferMap.rows ||
        waferMap.rows.length === 0
    ) {
        container.innerHTML =
            '<div class="empty-state">Waiting for wafer data...</div>';
        return;
    }


    const columns = waferMap.columns || [];

    const tdIndex = columns.indexOf('td');
    const siteIndex = columns.indexOf('site');
    const xIndex = columns.indexOf('x');
    const yIndex = columns.indexOf('y');
    const sbinIndex = columns.indexOf('sbin');
    const passedIndex = columns.indexOf('passed');
    const suspectIndex = columns.indexOf('suspect');


    const testedDies = new Map();

    waferMap.rows.forEach(row => {

        const x = row[xIndex];
        const y = row[yIndex];

        testedDies.set(`${x},${y}`, {
            td: row[tdIndex],
            site: row[siteIndex],
            x: x,
            y: y,
            sbin: row[sbinIndex],
            passed: row[passedIndex],
            suspect: row[suspectIndex]
        });
    });


    const allDies = waferLayout.map(([x, y]) => {

        const tested =
            testedDies.get(`${x},${y}`);

        // Not tested yet
        if (!tested) {
            return {
                td: null,
                site: null,
                x: x,
                y: y,
                sbin: null,
                passed: null,
                suspect: false,
                tested: false,
                color: '#e1e5eb'
            };
        }


        let color = '#22c55e';

        if (!tested.passed) {
            color = '#ef4444';
        } else if (tested.suspect) {
            color = '#f59e0b';
        }

        return {
            ...tested,
            tested: true,
            color: color
        };
    });


    const extent = waferMap.extent;

    let minX;
    let maxX;
    let minY;
    let maxY;

    if (extent) {
        minX = extent.x[0];
        maxX = extent.x[1];
        minY = extent.y[0];
        maxY = extent.y[1];
    } else {
        const xs = allDies.map(die => die.x);
        const ys = allDies.map(die => die.y);

        minX = Math.min(...xs);
        maxX = Math.max(...xs);
        minY = Math.min(...ys);
        maxY = Math.max(...ys);
    }


    const cellSize = 40;
    const gap = 5;
    const padding = 20;

    const width =
        (maxX - minX + 1) * (cellSize + gap) + padding * 2;

    const height =
        (maxY - minY + 1) * (cellSize + gap) + padding * 2;


    let svg =
        `<svg viewBox="0 0 ${width} ${height}"
            xmlns="http://www.w3.org/2000/svg">`;


    allDies.forEach(die => {

        const x =
            padding + (die.x - minX) * (cellSize + gap);

        const y =
            padding + (die.y - minY) * (cellSize + gap);

        let status;

        if (!die.tested) {
            status = 'Not tested';
        } else if (!die.passed) {
            status = 'Fail';
        } else if (die.suspect) {
            status = 'Suspect';
        } else {
            status = 'Pass';
        }

        let tooltip;

        if (!die.tested) {

            tooltip =
                `(${die.x}, ${die.y}) | Not tested`;

        } else {

            tooltip =
                `TD ${die.td ?? '-'} | ` +
                `Site ${die.site ?? '-'} | ` +
                `(${die.x}, ${die.y}) | ` +
                `Bin ${die.sbin ?? '-'} | ` +
                `${status}`;
        }

        svg += `
            <rect
                class="wafer-die"
                data-td="${die.td ?? ''}"
                data-site="${die.site ?? ''}"
                x="${x}"
                y="${y}"
                width="${cellSize}"
                height="${cellSize}"
                rx="5"
                fill="${die.color}">
                <title>${tooltip}</title>
            </rect>
        `;
    });


    svg += '</svg>';
    container.innerHTML = svg;
    updateWaferHighlight();
}

function renderCriteria(criteria) {
    if (!criteria || criteria.length === 0) {
        return;
    }
    const config = {
        mean_trend: {
            valueId: 'criteria-mean-value',
            thresholdId: 'criteria-mean-threshold',
            barId: 'criteria-mean-bar',
            overId: 'criteria-mean-over',
            unit: 'tests'
        },
        site_unbalance: {
            valueId: 'criteria-site-value',
            thresholdId: 'criteria-site-threshold',
            barId: 'criteria-site-bar',
            overId: 'criteria-site-over',
            unit: 'tests'
        },
        stdev_up: {
            valueId: 'criteria-stdev-value',
            thresholdId: 'criteria-stdev-threshold',
            barId: 'criteria-stdev-bar',
            overId: 'criteria-stdev-over',
            unit: 'tests'
        },
        yield: {
            valueId: 'criteria-yield-value',
            thresholdId: 'criteria-yield-threshold',
            barId: 'criteria-yield-bar',
            overId: 'criteria-yield-over',
            unit: '%'
        }
    };
    criteria.forEach(item => {
        const setting = config[item.key];
        if (!setting) {
            return;
        }
        const valueElement =
            document.getElementById(setting.valueId);
        const thresholdElement =
            document.getElementById(setting.thresholdId);
        const barElement =
            document.getElementById(setting.barId);
        const overElement =
            document.getElementById(setting.overId);
        if (
            !valueElement ||
            !thresholdElement ||
            !barElement
        ) {
            return;
        }
        // ----- Display value -----
        if (item.key === 'yield') {
            valueElement.textContent =
                item.value != null
                    ? `${(item.value * 100).toFixed(1)}%`
                    : '-';
            thresholdElement.textContent =
                item.threshold != null
                    ? `${(item.threshold * 100).toFixed(0)}%`
                    : '-';
        } else {
            valueElement.textContent =
                item.value != null
                    ? `${item.value} tests`
                    : '-';
            thresholdElement.textContent =
                item.threshold != null
                    ? item.threshold
                    : '-';
        }
        // ----- Progress bar -----
        if (
            item.value == null ||
            item.threshold == null ||
            item.threshold === 0
        ) {
            barElement.style.width = '0%';
            return;
        }
        // How much space represents the threshold.
        // If value exceeds threshold, leave room to show the excess.
        let maxValue = Math.max(
            item.threshold,
            item.value
        );
        // Add some space after the current value
        if (item.value > item.threshold) {
            maxValue = item.value * 1.15;
        }
        const thresholdPosition =
            (item.threshold / maxValue) * 100;
        const valuePosition =
            (item.value / maxValue) * 100;
        // Gray part: from 0 to threshold/current value
        barElement.style.width =
            `${Math.min(valuePosition, thresholdPosition)}%`;
        // Threshold line
        const thresholdLine =
            barElement.parentElement.querySelector(
                '.criteria-threshold-line'
            );
        thresholdLine.style.left =
            `${thresholdPosition}%`;
        // Red excess part
        if (
            item.trigger_when === 'at_least' &&
            item.value >= item.threshold
        ) {
            overElement.style.left =
                `${thresholdPosition}%`;
            overElement.style.width =
                `${valuePosition - thresholdPosition}%`;
        } else {
            overElement.style.width = '0%';
        }
        // ----- State -----
        barElement.classList.remove(
            'triggered',
            'normal',
            'insufficient'
        );
        if (
            item.key === 'yield' &&
            item.enough_data === false
        ) {
            barElement.classList.add('insufficient');
        } else if (item.triggered) {
            barElement.classList.add('triggered');
        } else {
            barElement.classList.add('normal');
        }
    });
}

async function updateDashboard() {
    try {
        const response = await fetch('/api/state');
        if (!response.ok) {
            throw new Error('Failed to load dashboard state');
        }
        const state = await response.json();

        const currentWafer =
            state.wafers?.find(
                wafer => wafer.current === true
            );

        if (currentWafer) {
            renderCriteria(currentWafer.criteria);
        }

        document.getElementById('lot').textContent =
            state.lot ?? '-';

        document.getElementById('wafer').textContent =
            state.wafer ?? '-';

        document.getElementById('touchdown').textContent =
            state.touchdown ?? 0;


        const triggeredCriteria =
            (state.indicators || [])
                .filter(item => item.triggered);


        const overallStatus =
            document.getElementById('overall-status');

        const statusIcon =
            document.getElementById('status-icon');

        const statusTitle =
            document.getElementById('status-title');

        const statusDescription =
            document.getElementById('status-description');


        const anomalyLabel = state.label;

        const hasAnomaly =
            anomalyLabel &&
            anomalyLabel.toLowerCase() !== 'normal';

        if (hasAnomaly) {

            overallStatus.classList.add('anomaly');

            statusIcon.textContent = '!';
            statusTitle.textContent = 'Attention Needed';

            statusDescription.textContent =
                `${anomalyLabel} detected on this wafer.`;

        } else {

            overallStatus.classList.remove('anomaly');

            statusIcon.textContent = '✓';
            statusTitle.textContent = 'No Anomalies Detected';

            statusDescription.textContent =
                'No anomalies have been detected on this wafer.';
        }


        const reportNormal =
            document.getElementById('report-normal');

        const reportAnomaly =
            document.getElementById('report-anomaly');

        const reportTitle =
            document.getElementById('report-title');

        const reportDescription =
            document.getElementById('report-description');


       if (hasAnomaly) {

            reportNormal.style.display = 'none';
            reportAnomaly.style.display = 'flex';

            reportTitle.textContent =
                anomalyLabel;

            reportDescription.textContent =
                'The detector identified an abnormal production pattern.';


            const onsetValues =
                triggeredCriteria
                    .map(item => item.detail?.onset_td)
                    .filter(value => value != null);

            const firstOnset =
                onsetValues.length > 0
                    ? Math.min(...onsetValues)
                    : null;


            document.getElementById('affected-sites').textContent =
                firstOnset != null
                    ? `Detected from Touchdown ${firstOnset}`
                    : 'Detected anomaly';


            document.getElementById('detail-touchdown').textContent =
                firstOnset ?? '-';

            document.getElementById('detail-alert-count').textContent =
                triggeredCriteria.length;


            const alertList =
                document.getElementById('alert-list');

            alertList.innerHTML = '';


            triggeredCriteria.forEach(item => {

                const card =
                    document.createElement('div');

                card.className = 'alert-detail-card';

                const direction =
                    item.detail?.direction ?? '-';

                const group =
                    item.detail?.group ?? '-';

                const onset =
                    item.detail?.onset_td ?? '-';

                card.innerHTML = `
                    <div class="alert-detail-header">
                        <strong>${item.name}</strong>
                    </div>

                    <div class="alert-detail-meta">
                        <span>Value: ${item.value ?? '-'}</span>
                        <span>Threshold: ${item.threshold ?? '-'}</span>
                        <span>Direction: ${direction}</span>
                        <span>Group: ${group}</span>
                        <span>Onset: TD ${onset}</span>
                    </div>
                `;

                alertList.appendChild(card);
            });

        } else {

            reportNormal.style.display = 'block';
            reportAnomaly.style.display = 'none';
        }


        renderTimeline(
            state.wafer_map,
            state.touchdown
        );
        renderWaferMap(state.wafer_map);


        // Reset all sites to normal
        for (let site = 1; site <= 4; site++) {
            const card = document.getElementById('site-' + site);

            card.classList.remove('alert');
            card.querySelector('.site-status').textContent = 'Normal';
        }


        const warningBox =
            document.getElementById('warning');

        const loadError = state.error;

        if (loadError) {

            warningBox.style.display = 'block';

            warningBox.textContent =
                'Detector Warning: ' + loadError;

        } else {

            warningBox.style.display = 'none';

        }


        document.getElementById('error').textContent = '';

    } catch (error) {

        document.getElementById('error').textContent =
            'Dashboard update failed: ' + error.message;

    }
}


const aiButton =
    document.getElementById('ai-button');

const aiBox =
    document.getElementById('ai-box');

const aiClose =
    document.getElementById('ai-close');


aiButton.addEventListener('click', () => {
    aiBox.classList.toggle('open');
});


aiClose.addEventListener('click', () => {
    aiBox.classList.remove('open');
});

const aiInput =
    document.getElementById('ai-input');

const aiSend =
    document.getElementById('ai-send');

const aiMessages =
    document.getElementById('ai-messages');


function addAIMessage(text, type) {

    const message =
        document.createElement('div');

    message.className =
        `ai-message ${type}`;

    message.textContent = text;

    aiMessages.appendChild(message);

    aiMessages.scrollTop =
        aiMessages.scrollHeight;
}

async function sendAIMessage() {

    const question =
        aiInput.value.trim();

    if (!question) {
        return;
    }

    addAIMessage(question, 'user');

    aiInput.value = '';

    addAIMessage(
        'Thinking...',
        'assistant'
    );

    const thinkingMessage =
        aiMessages.lastElementChild;

    try {

        const response = await fetch('/api/chat', {
            method: 'POST',

            headers: {
                'Content-Type': 'application/json'
            },

            body: JSON.stringify({
                question: question
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(
                data.error || 'AI request failed'
            );
        }

        thinkingMessage.textContent =
            data.answer;

    } catch (error) {

        thinkingMessage.textContent =
            'Unable to get an AI response: ' +
            error.message;

    }

    aiMessages.scrollTop =
        aiMessages.scrollHeight;
}


aiSend.addEventListener('click', sendAIMessage);


aiInput.addEventListener('keydown', event => {

    if (event.key === 'Enter') {
        sendAIMessage();
    }

});

document
    .querySelectorAll('.ai-suggestion')
    .forEach(button => {

        button.addEventListener('click', () => {

            aiInput.value =
                button.textContent.trim();

            sendAIMessage();

        });

    });

document
    .querySelectorAll('.site-item')
    .forEach(item => {

        const site = Number(item.dataset.site);

        item.addEventListener('mouseenter', () => {

            // 已經固定 Site 時，不接受 hover
            if (selectedSite !== null) {
                return;
            }

            hoveredSite = site;
            updateWaferHighlight();
        });

        item.addEventListener('mouseleave', () => {

            // 已經固定 Site 時，不接受 hover
            if (selectedSite !== null) {
                return;
            }

            hoveredSite = null;
            updateWaferHighlight();
        });

        item.addEventListener('click', () => {

            hoveredSite = null;

            if (selectedSite === site) {
                // 再點一次目前 Site → 取消
                selectedSite = null;
            } else {
                // 固定新的 Site
                selectedSite = site;
            }

            updateSiteSelection();
            updateWaferHighlight();
        });
    });

updateDashboard();

setInterval(updateDashboard, 1000);
