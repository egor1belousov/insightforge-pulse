"""Служебная панель для внутренней отладки (не для пользователей): `make admin`."""

import pandas as pd
import streamlit as st
from sqlalchemy import text

from app.db.session import engine

st.set_page_config(page_title="Пульс · отладка", layout="wide")
st.title("Пульс адаптации — служебная панель")
st.caption("Только для команды. Пользовательский интерфейс — в приложении.")

TABLES = [
    "pairs",
    "participants",
    "responses",
    "signals",
    "health_snapshots",
    "comment_analysis",
    "actions",
    "import_jobs",
    "settings",
]
name = st.sidebar.selectbox("Таблица", TABLES)
with engine.connect() as conn:
    df = pd.read_sql(text(f"SELECT * FROM {name} ORDER BY 1 DESC LIMIT 500"), conn)
st.write(f"{name}: {len(df)} строк (последние 500)")
st.dataframe(df, use_container_width=True)
