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
    """
    Fetches data from the 'products' table, including availability configuration.
    The 'available_from', 'available_to', and 'allow_negative' columns are now expected
    to be directly on the 'products' table.
    """
    try:
        logging.info("Fetching data from 'products' table...")
        # Fetch all columns, assuming available_from, available_to, allow_negative are now in 'products'
        products_res = supabase.table("products").select("*").eq("organization_id", "c4f3eed9-de25-4a7a-9664-7674e16b5bfd").execute()
        df_products = pd.DataFrame(products_res.data)

        if 'code' not in df_products.columns:
            st.toast("Product table must have a 'code' column.", icon="⚠️")
            logging.error("Product table missing 'code' column.")
            return pd.DataFrame()

        # Ensure the new columns exist, providing defaults if they don't
        # This is crucial if the columns might not be present in the DB yet
        for col in ['available_from', 'available_to']:
            if col not in df_products.columns:
                df_products[col] = None
        if 'allow_negative' not in df_products.columns:
            df_products['allow_negative'] = False # Default to False if column doesn't exist

        # Apply formatting for editor display
        df_products['available_from'] = df_products['available_from'].apply(format_time_for_editor)
        df_products['available_to'] = df_products['available_to'].apply(format_time_for_editor)
        # Ensure 'allow_negative' is boolean, default to False if None/NaN
        df_products['allow_negative'] = df_products['allow_negative'].fillna(False).astype(bool)
        
        logging.info("Data fetched and processed successfully from 'products' table.")
        return df_products

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
    # Exclude time and boolean columns from initial selection for product columns
    product_columns = [col for col in st.session_state.original_data.columns if col not in ['available_from', 'available_to', 'allow_negative']]
    
    with st.expander("Display Options"):
        selected_columns = st.multiselect(
            "Choose product columns to display:",
            options=product_columns,
            default=['code', 'name']
        )

    # Always include the time and allow_negative columns
    display_columns = selected_columns + ['available_from', 'available_to', 'allow_negative']

    edited_df = st.data_editor(
        st.session_state.original_data,
        column_order=display_columns,
        column_config={
            "available_from": st.column_config.TimeColumn("Start Time", format="HH:mm"),
            "available_to": st.column_config.TimeColumn("End Time", format="HH:mm"),
            "allow_negative": st.column_config.CheckboxColumn("Allow Negative", default=False), # Configured as a checkbox/toggle
        },
        # Disable all columns except the editable ones
        disabled=[col for col in st.session_state.original_data.columns if col not in ['available_from', 'available_to', 'allow_negative']],
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

                # Check for changes in available_from, available_to, or allow_negative
                if (original_row['available_from'] != row['available_from'] or 
                    original_row['available_to'] != row['available_to'] or
                    original_row['allow_negative'] != row['allow_negative']):
                    
                    updates.append({
                        "code": product_code,
                        "available_from": format_time_for_db(row['available_from']),
                        "available_to": format_time_for_db(row['available_to']),
                        "allow_negative": bool(row['allow_negative']) # Ensure it's a boolean
                    })
                    logging.info(f"Change detected for '{product_code}': "
                                 f"Start: {row['available_from']}, End: {row['available_to']}, "
                                 f"Allow Negative: {row['allow_negative']}")

            if updates:
                try:
                    logging.info(f"Sending {len(updates)} updates to Supabase (products table).")
                    for update in updates:
                        # Update the 'products' table directly
                        # Only include the fields that are being updated
                        update_payload = {k: update[k] for k in ["available_from", "available_to", "allow_negative"]}
                        supabase.table("products").update(update_payload).eq("code", update['code']).execute()
                    st.toast(f"Saved changes for {len(updates)} product(s).", icon="✅")
                    logging.info("Supabase update successful for 'products' table.")
                    
                    # Update original_data in session state to reflect the saved changes
                    # This ensures that the next comparison correctly identifies only new changes.
                    st.session_state.original_data = edited_df.copy()

                except Exception as e:
                    st.toast(f"Error saving to Supabase: {e}", icon="🔥")
                    logging.error(f"Supabase update failed for 'products' table: {e}", exc_info=True)
            else:
                st.toast("No changes to save.", icon="🤷")
            
    with col2:
        if st.button("Logout", use_container_width=False):
            logging.info(f"User '{st.session_state.get('username', 'unknown')}' logged out.")
            for key in ['logged_in', 'login_time', 'username']:
                if key in st.session_state:
                    del st.session_state[key]
            st.toast("Logged out.", icon="👋")
            st.rerun()

# --- Login and Session Management ---

def login_page():
    
    
    _, col1, _ = st.columns([1, 1, 1])

    with col1:
        st.title("Admin Login")
        username = st.text_input("Username", key="username_input")
        password = st.text_input("Password", type="password", key="password_input")
        
        if st.button("Login", key="login_button"):
            if username == "admin" and password == "admin1234":
                st.session_state.logged_in = True
                st.session_state.login_time = datetime.now()
                st.session_state.username = username
                st.toast("Logged in successfully!", icon="✅")
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