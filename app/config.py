import os
from dotenv import load_dotenv

# More robust Streamlit handling
USE_STREAMLIT_SECRETS = False
st = None

try:
    import streamlit as st
    # Only set to True if we can actually access secrets
    try:
        # Test if secrets are available
        test_access = st.secrets
        USE_STREAMLIT_SECRETS = True
        print("✅ Using Streamlit secrets")
    except Exception as e:
        print(f"⚠️ Streamlit imported but secrets not available: {e}")
        USE_STREAMLIT_SECRETS = False
        st = None
except ImportError as e:
    print(f"📝 Streamlit not available: {e}")
    USE_STREAMLIT_SECRETS = False
    st = None

# Always try to load .env as fallback
try:
    load_dotenv()
    print("✅ Loaded .env file")
except Exception as e:
    print(f"⚠️ Could not load .env: {e}")

def get_secret(key, default=None):
    """Get secret with bulletproof error handling"""
    # Try Streamlit secrets first (only if available)
    if USE_STREAMLIT_SECRETS and st is not None:
        try:
            if key in st.secrets:
                print(f"✅ Got {key} from Streamlit secrets")
                return st.secrets[key]
        except Exception as e:
            print(f"⚠️ Error accessing Streamlit secret {key}: {e}")
    
    # Fallback to environment variables
    env_value = os.getenv(key, default)
    if env_value:
        print(f"✅ Got {key} from environment")
    else:
        print(f"❌ {key} not found in environment")
    
    return env_value

# Load configuration
print("🔧 Loading configuration...")
SERPAPI_KEY = get_secret("SERPAPI_KEY")
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
#MODEL = "gpt-4o-mini"
MODEL = "gpt-4.1-mini-2025-04-14"
NUM_SOURCES = 10