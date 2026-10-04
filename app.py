def clean(h):
    return " ".join(line.strip() for line in h.splitlines())


data = st.session_state.data
if data:
    records = data["records"]
    user_color = data["user_color"]

    st.markdown(clean(data["status"]), unsafe_allow_html=True)
    st.markdown(clean(summary_html(records, user_color)), unsafe_allow_html=True)

    if len(records) > 1:
        st.slider("رقم النقلة", 0, len(records) - 1, key="idx")

    c1, c2 = st.columns(2)
    c1.button("◀ السابقة", on_click=go_prev, use_container_width=True)
    c2.button("التالية ▶", on_click=go_next, use_container_width=True)
    c3, c4 = st.columns(2)
    c3.button("خطئي التالي", on_click=go_mistake, use_container_width=True)
    c4.button("أسوأ خطأ", on_click=go_worst, use_container_width=True)

    idx = max(0, min(st.session_state.idx, len(records) - 1))
    st.markdown(clean(board_html(records, idx, user_color)), unsafe_allow_html=True)
