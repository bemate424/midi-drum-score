"""Streamlit UI: upload an SMF, run the drum-transcription pipeline, preview and
download the rendered PDF. Local-only tool — no auth, no multi-user handling.
"""

import tempfile
from pathlib import Path

import fitz
import streamlit as st

from pipeline.extract import extract_drum_events
from pipeline.musicxml_gen import build_musicxml
from pipeline.quantize import QuantizeOptions, quantize_events, snap_stray_offbeats
from pipeline.render import render_musicxml

st.set_page_config(page_title="MIDI → 드럼 악보", page_icon="🎵", layout="wide")

CSS = """
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css');

html, body, [class*="css"] {
    font-family: 'Pretendard', ui-sans-serif, system-ui, sans-serif;
}
.stApp {
    background-color: #f2f0eb;
    color: #292827;
}
h1, h2, h3 {
    font-weight: 460 !important;
    letter-spacing: -0.014em;
    color: #292827;
}

/* hide the auto-generated heading anchor-link icon (non-functional here -
   there's no multi-page/section routing to link to) */
[data-testid="stHeaderActionElements"],
h1 a, h2 a, h3 a {
    display: none !important;
}
p, li, span, label, div {
    color: #292827;
}
.block-container {
    max-width: 1200px;
    padding-top: 2.5rem;
}

/* card-like containers (st.expander and st.status both render as stExpander) */
div[data-testid="stExpander"], div[data-testid="stFileUploader"], div[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #ffffff;
    border: 1px solid #e3e3e2;
    border-radius: 16px;
}
div[data-testid="stFileUploader"] { padding: 16px; }

/* primary CTA button: Midnight Wine fill */
.stButton > button, .stDownloadButton > button {
    background-color: #421d24;
    color: #ffffff;
    border: none;
    border-radius: 16px;
    font-weight: 460;
    padding: 0.6rem 1.4rem;
}
.stButton > button *, .stDownloadButton > button * {
    color: #ffffff !important;
}
.stButton > button:hover, .stDownloadButton > button:hover {
    background-color: #5a2a33;
    color: #ffffff;
}

/* sidebar */
section[data-testid="stSidebar"] {
    background-color: #ffffff;
    border-right: 1px solid #e3e3e2;
}

/* stepper -/+ buttons: bare arrow glyphs, no filled box */
section[data-testid="stSidebar"] .stButton > button,
section[data-testid="stSidebar"] .stButton > button * {
    background-color: transparent !important;
    border: none !important;
    box-shadow: none !important;
    color: #421d24 !important;
    font-size: 20px !important;
    padding: 0 !important;
    margin: 0 auto !important;
    display: flex !important;
    justify-content: center !important;
    width: 100% !important;
}
/* keep both stepper columns and the slider vertically/horizontally aligned */
section[data-testid="stSidebar"] .stButton {
    display: flex !important;
    justify-content: center !important;
}
section[data-testid="stSidebar"] .stButton > button:hover,
section[data-testid="stSidebar"] .stButton > button:hover * {
    background-color: transparent !important;
    color: #714cb6 !important;
}

/* links */
a { color: #714cb6 !important; }

hr { border-color: #e3e3e2; }

.caption-text { color: #666666; font-size: 14px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown("# 🥁 MIDI → 드럼 악보")
st.markdown(
    '<p class="caption-text">SMF 파일을 업로드하면 드럼 채널만 추출해 박자를 보정하고 '
    "MusicXML로 변환한 뒤 MuseScore로 렌더링해 PDF 악보를 만듭니다. (로컬 전용 도구)</p>",
    unsafe_allow_html=True,
)

def stepper_slider(label, min_v, max_v, default, step, key):
    """A slider flanked by -/+ buttons for one-click fine adjustment."""
    if key not in st.session_state:
        st.session_state[key] = default
    col_minus, col_slider, col_plus = st.columns([1, 6, 1], vertical_alignment="center")
    with col_minus:
        if st.button("◀", key=f"{key}_dec"):
            st.session_state[key] = max(min_v, st.session_state[key] - step)
    with col_plus:
        if st.button("▶", key=f"{key}_inc"):
            st.session_state[key] = min(max_v, st.session_state[key] + step)
    with col_slider:
        st.session_state[key] = st.slider(
            label, min_v, max_v, st.session_state[key], step=step, label_visibility="collapsed"
        )
    return st.session_state[key]


with st.sidebar:
    st.markdown("### 옵션")
    st.markdown("**박자 그리드**")
    grid_label = st.selectbox(
        "박자 그리드",
        ["4분음표", "8분음표", "16분음표", "32분음표"],
        index=1,
        label_visibility="collapsed",
    )
    slots_per_quarter = {"4분음표": 1, "8분음표": 2, "16분음표": 4, "32분음표": 8}[grid_label]

    st.markdown("**고스트 노트 세기 (velocity)**")
    st.caption("이 세기보다 약하게 친 노트는 악보에서 제외합니다.")
    ghost_threshold = stepper_slider("고스트 노트 컷오프", 0, 60, 20, 1, "ghost_threshold")

    st.markdown("**연타 간격 (ms)**")
    st.caption("같은 악기가 이 시간 안에 두 번 울리면 더 센 타격 하나만 남깁니다.")
    merge_window_ms = stepper_slider("연타 병합 간격", 0, 60, 30, 5, "merge_window_ms")

    st.markdown("---")
    st.markdown("**악보 크기**")
    st.caption("인쇄/화면에서 보이는 오선지·음표 크기를 조절합니다.")
    staff_size_percent = stepper_slider("악보 크기", 70, 150, 100, 10, "staff_size_percent")

    st.markdown("---")
    is_32nd_grid = grid_label == "32분음표"
    snap_offbeats = st.checkbox(
        "튀는 박자 자동 정리", value=is_32nd_grid, disabled=is_32nd_grid
    )
    if is_32nd_grid:
        snap_offbeats = True
    st.caption(
        "혼자 튀는 당김음(주변에 반복되지 않는 박자 오차)만 가까운 정박으로 당깁니다. "
        "32분음표 그리드에서는 잔타이밍 오차가 노트로 잡히기 쉬워서 항상 켜져 있습니다."
    )

    st.markdown("---")
    st.markdown(
        '<p class="caption-text">GM 드럼 채널(채널 10)만 인식합니다.</p>',
        unsafe_allow_html=True,
    )

uploaded = st.file_uploader("SMF 파일 업로드 (.mid, .midi)", type=["mid", "midi"])

if "work_dir" not in st.session_state:
    st.session_state.work_dir = tempfile.mkdtemp(prefix="drumscore_")

if uploaded is not None:
    work_dir = Path(st.session_state.work_dir)
    midi_path = work_dir / uploaded.name
    midi_path.write_bytes(uploaded.getvalue())

    if st.button("변환 시작"):
        with st.status("변환 진행 중...", expanded=True) as status:
            status.update(label="1/4 · 드럼 데이터를 추출하는 중...")
            extraction = extract_drum_events(str(midi_path))

            if not extraction.events:
                status.update(label="드럼 채널을 찾지 못했습니다", state="error")
                st.error("드럼 채널(채널 10)에서 노트를 찾지 못했습니다.")
            else:
                st.write(f"추출된 이벤트 {len(extraction.events)}개 · 템포 {extraction.tempo_bpm:.1f} BPM · 박자 {extraction.time_signature[0]}/{extraction.time_signature[1]}")

                status.update(label="2/4 · 박자를 보정하는 중...")
                options = QuantizeOptions(
                    subdivisions_per_quarter=slots_per_quarter,
                    ghost_velocity_threshold=ghost_threshold,
                    merge_window_sec=merge_window_ms / 1000,
                )
                quantized = quantize_events(
                    extraction.events, extraction.tempo_bpm, extraction.time_signature, options
                )
                measures = quantized.measures
                if snap_offbeats:
                    measures = snap_stray_offbeats(measures, slots_per_quarter, quantized.velocities)
                st.write(f"{len(measures)}마디로 보정 완료")

                status.update(label="3/4 · MusicXML을 생성하는 중...")
                xml = build_musicxml(
                    measures,
                    extraction.time_signature,
                    extraction.tempo_bpm,
                    slots_per_quarter,
                    title=midi_path.stem,
                    staff_size_percent=staff_size_percent,
                )
                musicxml_path = work_dir / f"{midi_path.stem}.musicxml"
                musicxml_path.write_text(xml, encoding="utf-8")
                st.write("MusicXML 생성 완료")

                status.update(label="4/4 · MuseScore로 PDF를 렌더링하는 중...")
                pdf_path = work_dir / f"{midi_path.stem}.pdf"
                try:
                    render_musicxml(str(musicxml_path), str(pdf_path))
                    st.session_state.pdf_path = str(pdf_path)
                    st.session_state.musicxml_path = str(musicxml_path)
                    status.update(label="변환 완료!", state="complete")
                except Exception as exc:
                    status.update(label="렌더링 실패", state="error")
                    st.error(f"렌더링 실패: {exc}")

        if extraction.events:
            with st.expander(f"1단계 · 추출된 드럼 이벤트 ({len(extraction.events)}개)"):
                st.dataframe(
                    [
                        {"시간(초)": round(e.time_sec, 3), "노트": e.note, "악기": e.name, "세기": e.velocity}
                        for e in extraction.events[:500]
                    ],
                    use_container_width=True,
                )
            with st.expander(f"2단계 · 보정된 그리드 ({len(measures)}마디)"):
                for m_idx, measure in enumerate(measures[:8], start=1):
                    st.write(f"마디 {m_idx}: {measure}")
                if len(measures) > 8:
                    st.caption(f"... 외 {len(measures) - 8}마디 생략")
            with st.expander("3단계 · 생성된 MusicXML"):
                st.code(xml, language="xml")

if st.session_state.get("pdf_path"):
    st.markdown("### 4단계 · 미리보기 및 다운로드")
    pdf_path = Path(st.session_state.pdf_path)
    doc = fitz.open(str(pdf_path))
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        st.image(pix.tobytes("png"), use_container_width=True)
    doc.close()

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "PDF 다운로드", pdf_path.read_bytes(), file_name=pdf_path.name, mime="application/pdf"
        )
    with col2:
        musicxml_path = Path(st.session_state.musicxml_path)
        st.download_button(
            "MusicXML 다운로드",
            musicxml_path.read_bytes(),
            file_name=musicxml_path.name,
            mime="application/vnd.recordare.musicxml+xml",
        )
    st.caption("수정이 필요하면 MusicXML을 MuseScore에서 직접 열어 편집한 뒤 PDF로 내보낼 수 있습니다.")
