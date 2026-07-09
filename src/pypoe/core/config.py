import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path

@dataclass
class Config:
    """Configuration class for PyPoe using official Poe API."""
    poe_api_key: str = ""
    database_path: str = ""
    web_username: str = ""       # vestigial: Basic-auth retired in favour of the ac_auth edge (§4.8)
    web_password: str = ""       # vestigial: see web_username
    # Trust the ``X-Auth-User`` header from the ac_auth Caddy edge as the
    # signed-in identity (owner-scopes the web UI, §4.8). Leave FALSE until the
    # web port is only reachable through that edge — otherwise the header is
    # spoofable on a directly-reachable port. Enable with PYPOE_TRUST_FORWARD_AUTH=true.
    web_trust_forward_auth: bool = False
    # Cookie-verify auth (§4.8, the no-Caddy path used today): validate the
    # request's ac_auth_session cookie against the sidecar's GET /auth/verify
    # (like the dashboard's Next.js middleware) and owner-scope per user. Gates
    # reads too, since PyPoe's reads are private per-user chat. Default off;
    # enable with PYPOE_AUTH_VERIFY_COOKIE=true.
    web_auth_verify_cookie: bool = False
    # ac_auth sidecar base URL. NB it binds the Tailnet interface, not loopback
    # (127.0.0.1:8009 is refused), so default to the tailnet address.
    web_auth_service_base: str = "http://100.64.254.6:8009"
    # Where to send an unauthenticated browser (the dashboard hosts the
    # LoginBar, which sets the shared ac_auth_session cookie). Empty => 401.
    web_login_url: str = ""
    # Canonical host:port to redirect browser navigations to (§4.8), so the
    # ac_auth_session domain cookie attaches — it is never sent to a raw IP.
    # Only HTML GETs are redirected; empty => no redirect. Set via
    # PYPOE_CANONICAL_HOST, e.g. sdl2-server-gaia.tail6a1dd7.ts.net:8006.
    web_canonical_host: str = ""
    # Auto-download images/videos referenced in assistant replies. Disabled by
    # default so chat-only deployments don't need aiohttp. Enable with
    # PYPOE_ENABLE_MEDIA=true and install the [media] extra.
    enable_media: bool = False
    # Hide model reasoning blocks from Slack display while keeping full
    # responses in history. Enable with PYPOE_SLACK_HIDE_THINKING=true.
    slack_hide_thinking: bool = False

    def __post_init__(self):
        # Try to load .env from multiple locations
        self._load_env_files()

        # Set default database path to user-specific directory (~/.pypoe/)
        default_db_path = os.path.expanduser("~/.pypoe/single_webchat_history.db")

        self.poe_api_key = os.getenv("POE_API_KEY", self.poe_api_key)
        self.database_path = os.getenv("DATABASE_PATH", default_db_path)
        self.web_username = os.getenv("PYPOE_WEB_USERNAME", self.web_username)
        self.web_password = os.getenv("PYPOE_WEB_PASSWORD", self.web_password)
        self.enable_media = _parse_bool(os.getenv("PYPOE_ENABLE_MEDIA"), self.enable_media)
        self.web_trust_forward_auth = _parse_bool(
            os.getenv("PYPOE_TRUST_FORWARD_AUTH"), self.web_trust_forward_auth
        )
        self.web_auth_verify_cookie = _parse_bool(
            os.getenv("PYPOE_AUTH_VERIFY_COOKIE"), self.web_auth_verify_cookie
        )
        self.web_auth_service_base = os.getenv(
            "PYPOE_AUTH_SERVICE_BASE", self.web_auth_service_base
        )
        self.web_login_url = os.getenv("PYPOE_LOGIN_URL", self.web_login_url)
        self.web_canonical_host = os.getenv(
            "PYPOE_CANONICAL_HOST", self.web_canonical_host
        )
        self.slack_hide_thinking = _parse_bool(
            os.getenv("PYPOE_SLACK_HIDE_THINKING"),
            self.slack_hide_thinking,
        )

        # Ensure the ~/.pypoe directory exists
        pypoe_dir = Path(self.database_path).parent
        pypoe_dir.mkdir(parents=True, exist_ok=True)

        if not self.poe_api_key:
            raise ValueError(
                "POE_API_KEY is not set. Please get your API key from https://poe.com/api_key "
                "and set it in your .env file or environment variables."
            )

    def _load_env_files(self):
        """Load .env files from multiple possible locations."""
        # core/config.py -> core/ -> pypoe/ -> src/ -> repo root
        repo_root = Path(__file__).parent.parent.parent.parent
        possible_env_paths = [
            # 1. Repo root (where developers typically put the .env file)
            repo_root / ".env",
            # 2. User config directory
            Path.home() / ".pypoe" / ".env",
            # 3. Current working directory
            Path.cwd() / ".env",
        ]

        for env_path in possible_env_paths:
            if env_path.exists():
                print(f"Loading environment from: {env_path}")
                load_dotenv(env_path)
                break
        else:
            # No .env file found, try loading from environment anyway
            load_dotenv()

def _parse_bool(value, default: bool) -> bool:
    """Parse a string env var as a boolean, falling back to ``default``."""
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_config() -> Config:
    """Get the application configuration."""
    return Config()
