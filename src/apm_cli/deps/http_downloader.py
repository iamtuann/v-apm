"""HTTP archive and directory download support for APM packages.

Supports:
- Archive files: .zip, .tar.gz, .tgz, .tar.bz2, .tar.xz
- Directory listings: HTML index pages from http.server or similar
"""

from __future__ import annotations

import re
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from apm_cli.utils.console import _rich_warning


# Archive extensions we support
ARCHIVE_EXTENSIONS = ('.zip', '.tar.gz', '.tgz', '.tar.bz2', '.tar.xz')


def is_http_archive_url(url: str) -> bool:
    """Check if URL points to an archive file.
    
    Args:
        url: URL to check
        
    Returns:
        True if URL ends with a known archive extension
    """
    if not url.startswith(('http://', 'https://')):
        return False
    url_lower = url.lower()
    return any(url_lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def is_http_directory_url(url: str) -> bool:
    """Check if URL might be a directory listing.
    
    Args:
        url: URL to check
        
    Returns:
        True if URL is HTTP but not an archive
    """
    if not url.startswith(('http://', 'https://')):
        return False
    return not is_http_archive_url(url)


def download_file(url: str, dest: Path, timeout: int = 30) -> Path:
    """Download a file from URL to destination.
    
    Args:
        url: URL to download from
        dest: Destination path (file or directory)
        timeout: Request timeout in seconds
        
    Returns:
        Path to downloaded file
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    
    response = requests.get(url, stream=True, timeout=timeout)
    response.raise_for_status()
    
    with open(dest, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return dest


def extract_archive(archive_path: Path, dest: Path) -> Path:
    """Extract an archive to destination directory.
    
    Supports: .zip, .tar.gz, .tgz, .tar.bz2, .tar.xz
    
    Args:
        archive_path: Path to archive file
        dest: Destination directory
        
    Returns:
        Path to extracted content (may be subdirectory)
    """
    dest.mkdir(parents=True, exist_ok=True)
    archive_name = archive_path.name.lower()
    
    if archive_name.endswith('.zip'):
        with zipfile.ZipFile(archive_path, 'r') as zf:
            zf.extractall(dest)
    elif archive_name.endswith(('.tar.gz', '.tgz')):
        with tarfile.open(archive_path, 'r:gz') as tf:
            tf.extractall(dest)
    elif archive_name.endswith('.tar.bz2'):
        with tarfile.open(archive_path, 'r:bz2') as tf:
            tf.extractall(dest)
    elif archive_name.endswith('.tar.xz'):
        with tarfile.open(archive_path, 'r:xz') as tf:
            tf.extractall(dest)
    else:
        raise ValueError(f"Unsupported archive format: {archive_path}")
    
    # If archive contains a single directory, return that
    contents = list(dest.iterdir())
    if len(contents) == 1 and contents[0].is_dir():
        return contents[0]
    
    return dest


def parse_directory_listing(html: str, base_url: str) -> list[tuple[str, bool]]:
    """Parse HTML directory listing and extract links.
    
    Handles common formats:
    - Python http.server
    - Nginx autoindex
    - Apache mod_autoindex
    
    Args:
        html: HTML content of directory listing
        base_url: Base URL for resolving relative links
        
    Returns:
        List of (name, is_directory) tuples
    """
    links = []
    
    # Pattern for <a href="..."> links
    href_pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\']', re.IGNORECASE)
    
    for match in href_pattern.finditer(html):
        href = match.group(1)
        
        # Skip parent directory links
        if href == '../' or href == '..':
            continue
        
        # Skip query strings and fragments
        if '?' in href or '#' in href:
            continue
        
        # Skip absolute URLs to different hosts
        if href.startswith(('http://', 'https://')):
            parsed_href = urlparse(href)
            parsed_base = urlparse(base_url)
            if parsed_href.netloc != parsed_base.netloc:
                continue
        
        # Determine if directory (ends with /)
        is_directory = href.endswith('/')
        
        # Clean up the name
        name = href.rstrip('/') if is_directory else href
        
        links.append((name, is_directory))
    
    return links


class HttpDirectoryDownloader:
    """Download a directory recursively via HTTP directory listing."""
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
    
    def download(self, url: str, dest: Path) -> Path:
        """Download a directory recursively.
        
        Args:
            url: Base URL of the directory
            dest: Local destination path
            
        Returns:
            Path to downloaded directory
        """
        dest.mkdir(parents=True, exist_ok=True)
        self._download_recursive(url, dest)
        return dest
    
    def _download_recursive(self, url: str, dest: Path) -> None:
        """Recursively download directory contents.
        
        Args:
            url: URL of current directory
            dest: Local destination for current directory
        """
        # Fetch directory listing
        try:
            response = requests.get(url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as e:
            _rich_warning(f"Failed to fetch {url}: {e}")
            return
        
        # Check if this is actually a file (not a directory listing)
        content_type = response.headers.get('Content-Type', '')
        if 'text/html' not in content_type:
            # This is a file, not a directory
            download_file(url, dest / url.split('/')[-1], self.timeout)
            return
        
        # Parse directory listing
        links = parse_directory_listing(response.text, url)
        
        if not links:
            # No links found - might be a file or empty directory
            # Try to save as file
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(response.content)
            return
        
        for name, is_directory in links:
            item_url = urljoin(url.rstrip('/') + '/', name)
            item_dest = dest / name
            
            if is_directory:
                # Recurse into subdirectory
                item_dest.mkdir(parents=True, exist_ok=True)
                self._download_recursive(item_url + '/', item_dest)
            else:
                # Download file
                try:
                    download_file(item_url, item_dest, self.timeout)
                except requests.RequestException as e:
                    _rich_warning(f"Failed to download {item_url}: {e}")


class HttpArchiveDownloader:
    """Download and extract an archive via HTTP."""
    
    def __init__(self, timeout: int = 30, keep_cache: bool = False):
        self.timeout = timeout
        self.keep_cache = keep_cache
    
    def download(self, url: str, dest: Path) -> Path:
        """Download and extract an archive.
        
        Args:
            url: URL of the archive
            dest: Destination directory for extraction
            
        Returns:
            Path to extracted content
        """
        dest.mkdir(parents=True, exist_ok=True)
        
        # Determine archive filename from URL
        parsed = urlparse(url)
        archive_name = Path(parsed.path).name
        archive_ext = ''
        for ext in ARCHIVE_EXTENSIONS:
            if archive_name.lower().endswith(ext):
                archive_ext = ext
                break
        
        # Create temporary file for download
        with tempfile.NamedTemporaryFile(suffix=archive_ext, delete=not self.keep_cache) as tmp:
            tmp_path = Path(tmp.name)
            
            # Download archive
            download_file(url, tmp_path, self.timeout)
            
            # Extract
            extracted = extract_archive(tmp_path, dest)
            
            return extracted


def download_from_http(
    url: str,
    dest: Path,
    timeout: int = 30,
    keep_cache: bool = False,
) -> Path:
    """Download package from HTTP URL (archive or directory).
    
    Automatically detects whether URL is an archive file or directory listing.
    
    Args:
        url: HTTP URL to download from
        dest: Destination directory
        timeout: Request timeout in seconds
        keep_cache: Keep downloaded archive after extraction
        
    Returns:
        Path to downloaded/extracted package
    """
    if is_http_archive_url(url):
        downloader = HttpArchiveDownloader(timeout=timeout, keep_cache=keep_cache)
        return downloader.download(url, dest)
    else:
        downloader = HttpDirectoryDownloader(timeout=timeout)
        return downloader.download(url, dest)