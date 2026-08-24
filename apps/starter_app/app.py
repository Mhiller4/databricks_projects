"""
Starter Databricks App scaffold.

This file is intentionally minimal for v1. Replace placeholders with a real app
implementation once data products and UX requirements are defined.
"""

try:
    import streamlit as st
except ImportError:
    raise RuntimeError("Install streamlit to run this scaffolded app")

st.set_page_config(page_title="DAB Starter App", layout="wide")

st.title("DAB Starter App Scaffold")
st.write("This is a placeholder Databricks App for demonstration purposes.")

st.subheader("What to build next")
st.markdown(
    """
- Curated KPI dashboard
- Data quality status view
- Job run history and failure diagnostics
- Controlled export actions
"""
)
