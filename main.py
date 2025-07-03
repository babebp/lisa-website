import streamlit as st
from supabase import create_client, Client
import pandas as pd
import os
import logging
import time
from datetime import time as dt_time, datetime, timedelta
from dotenv import load_dotenv

# --- Basic Setup ---
load_dotenv(override=True)
st.set_page_config(page_title="Product Availability Editor", layout="wide")

# --- Logging Configuration ---
log_file = 'app.log'
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler() # To also see logs in the console
    ]
)

# --- Supabase Initialization ---
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    st.toast("Supabase URL or Key not set. Check .env file.", icon="🔥")
    logging.error("Supabase URL or Key not set.")
    st.stop()

try:
    supabase: Client = create_client(supabase_url, supabase_key)
    logging.info("Supabase client initialized successfully.")
except Exception as e:
    st.toast(f"Failed to connect to Supabase: {e}", icon="🔥")
    logging.error(f"Supabase initialization failed: {e}")
    st.stop()


# --- Data Handling Functions ---

def format_time_for_db(time_obj):
    """Converts a datetime.time object to a 'HH:MM:SS' string for Supabase."""
    return time_obj.strftime('%H:%M:%S') if isinstance(time_obj, dt_time) else None

def format_time_for_editor(time_str_from_db):
    """Converts a time string from DB to a datetime.time object for the editor."""
    if not time_str_from_db:
        return None
    try:
        return datetime.strptime(time_str_from_db, "%H:%M:%S").time()
    except (ValueError, TypeError):
        logging.warning(f"Could not parse time string '{time_str_from_db}'. Returning None.")
        return None

@st.cache_data(ttl=300)
def fetch_data():
    """Fetches and merges data from Supabase tables."""
    try:
        logging.info("Fetching data from Supabase...")
        products_res = supabase.table("products").select("*").execute()
        df_products = pd.DataFrame(products_res.data)

        if 'code' not in df_products.columns:
            st.toast("Product table must have a 'code' column.", icon="⚠️")
            logging.error("Product table missing 'code' column.")
            return pd.DataFrame()

        config_res = supabase.table("product_availability_config").select("code, start_time, end_time").execute()
        df_config = pd.DataFrame(config_res.data)

        for col in ['start_time', 'end_time']:
            if col not in df_config.columns:
                df_config[col] = None
        
        merged_df = pd.merge(df_products, df_config, on='code', how='left')
        
        merged_df['start_time'] = merged_df['start_time'].apply(format_time_for_editor)
        merged_df['end_time'] = merged_df['end_time'].apply(format_time_for_editor)
        
        logging.info("Data fetched and processed successfully.")
        return merged_df

    except Exception as e:
        st.toast(f"Error fetching data: {e}", icon="🔥")
        logging.error(f"Error in fetch_data: {e}", exc_info=True)
        return pd.DataFrame()

# --- Main Application UI ---

def main_app():
    st.title("Product Availability Editor")

    if 'original_data' not in st.session_state:
        st.session_state.original_data = fetch_data()
    
    if st.session_state.original_data.empty:
        st.warning("No data to display.")
        return

    # --- Column Selector ---
    product_columns = [col for col in st.session_state.original_data.columns if col not in ['start_time', 'end_time']]
    
    with st.expander("Display Options"):
        selected_columns = st.multiselect(
            "Choose product columns to display:",
            options=product_columns,
            default=['code', 'name']
        )

    # Always include the time columns
    display_columns = selected_columns + ['start_time', 'end_time']

    edited_df = st.data_editor(
        st.session_state.original_data,
        column_order=display_columns,
        column_config={
            "start_time": st.column_config.TimeColumn("Start Time", format="HH:mm"),
            "end_time": st.column_config.TimeColumn("End Time", format="HH:mm"),
        },
        disabled=[col for col in st.session_state.original_data.columns if col not in ['start_time', 'end_time']],
        hide_index=True,
        use_container_width=True,
        key="data_editor"
    )

    col1, col2, col3 = st.columns([1, 1, 5])

    with col1:
        if st.button("Save Changes", use_container_width=True):
            updates = []
            original_indexed = st.session_state.original_data.set_index('code')
            
            for index, row in edited_df.iterrows():
                product_code = row['code']
                original_row = original_indexed.loc[product_code]

                if original_row['start_time'] != row['start_time'] or original_row['end_time'] != row['end_time']:
                    updates.append({
                        "code": product_code,
                        "start_time": format_time_for_db(row['start_time']),
                        "end_time": format_time_for_db(row['end_time'])
                    })
                    logging.info(f"Change detected for '{product_code}': Start: {row['start_time']}, End: {row['end_time']}")

            if updates:
                try:
                    logging.info(f"Sending {len(updates)} updates to Supabase.")
                    for update in updates:
                        supabase.table("product_availability_config").update({k: update[k] for k in ["start_time", "end_time"]}).eq("code", update['code']).execute()
                    st.toast(f"Saved changes for {len(updates)} product(s).", icon="✅")
                    logging.info("Supabase upsert successful.")
                    st.cache_data.clear()
                    time.sleep(2) # Wait 2 seconds before rerunning
                    st.rerun()
                except Exception as e:
                    st.toast(f"Error saving to Supabase: {e}", icon="🔥")
                    logging.error(f"Supabase upsert failed: {e}", exc_info=True)
            else:
                st.toast("No changes to save.", icon="🤷")

    with col2:
        if st.button("Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.toast("Data refreshed.", icon="🔄")
            logging.info("Data cache cleared by user.")
            st.rerun()
            
    with col3:
        if st.button("Logout", use_container_width=False):
            logging.info(f"User '{st.session_state.get('username', 'unknown')}' logged out.")
            for key in ['logged_in', 'login_time', 'username']:
                if key in st.session_state:
                    del st.session_state[key]
            st.toast("Logged out.", icon="👋")
            st.rerun()

# --- Login and Session Management ---

def login_page():
    st.title("Admin Login")
    username = st.text_input("Username", key="username_input")
    password = st.text_input("Password", type="password", key="password_input")

    if st.button("Login", key="login_button"):
        if username == "admin" and password == "admin1234":
            st.session_state.logged_in = True
            st.session_state.login_time = datetime.now()
            st.session_state.username = username
            st.toast("Logged in successfully!", icon="🎉")
            logging.info(f"User '{username}' logged in successfully.")
            st.rerun()
        else:
            st.toast("Invalid username or password.", icon="❌")
            logging.warning(f"Failed login attempt for username: '{username}'.")

# --- Page Routing ---
session_is_active = False
if st.session_state.get('logged_in'):
    elapsed_time = datetime.now() - st.session_state.get('login_time', datetime.min)
    if elapsed_time < timedelta(minutes=5):
        session_is_active = True
    else:
        for key in ['logged_in', 'login_time', 'username']:
            if key in st.session_state:
                del st.session_state[key]
        st.toast("Session expired. Please log in again.", icon="⏳")
        logging.info("User session expired.")

if session_is_active:
    main_app()
else:
    login_page()