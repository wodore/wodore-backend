import base64
import hashlib
import hmac
from typing import Literal, Optional
from urllib.parse import quote as url_quote

import requests

from django.conf import settings
from django.db.models.fields.files import ImageFieldFile
from django.utils.html import format_html

# https://github.com/cshum/imagor

# Load environment variables for Imagor configurations


class TransformedImage:
    """Represents a transformed image with its URL and helper methods."""

    def __init__(self, url: str) -> None:
        """
        Initialize the TransformedImage class.

        Args:
            url: The URL of the transformed image.
        """
        self.url = url

    def get_html(self, alt_text: Optional[str] = "") -> str:
        """
        Generate an HTML img tag for the transformed image.

        Args:
            alt_text (Optional[str]): Alternative text for the image.

        Returns:
            str: The HTML img tag.
        """
        return format_html('<img src="{}" alt="{}"/>', self.url, alt_text)

    def get_full_url(self) -> str:
        """
        Return the full URL of the transformed image.

        Returns:
            str: The transformed image URL.
        """
        return self.url


class ImagorImage:
    """Handles image transformation logic using Imagor."""

    def __init__(self, image: str | ImageFieldFile) -> None:
        """
        Initialize the ImagorImage class with a Django Image object.

        Args:
            image (ImageFieldFile): The Django ImageFieldFile object.
        """
        if isinstance(image, ImageFieldFile):
            self.image_url = image.url
        else:
            self.image_url = image

    @classmethod
    def sign_path(
        cls,
        path: str,
        key: str | None = None,
        algorithmus: Literal["sha1", "sha256", "sha512"] = "sha256",
        quote: Literal["auto", "yes", "no"] = "auto",
    ) -> str:
        """
        Generate a HMAC-SHA256 signature for the path and return it in Base64.

        Args:
            path (str): The image URL path to sign.

        Returns:
            str: The signed path.
        """
        imagor_key = key or settings.IMAGOR_KEY
        safe_path = cls.url_quote(path, quote)
        # print(f"IMAGOR KEY: {key}")
        # hmac_digest = hmac.new(IMAGOR_SECRET.encode("utf-8"), path.encode("utf-8"), hashlib.sha256).digest()
        hmac_digest = hmac.new(
            imagor_key.encode("utf-8"),
            safe_path.encode("utf-8"),
            getattr(hashlib, algorithmus),
        ).digest()
        return base64.urlsafe_b64encode(hmac_digest).decode("utf-8")

    @classmethod
    def url_quote(
        cls, path: str, quote: Literal["auto", "yes", "no"] = "auto", safe=""
    ) -> str:
        if quote == "auto":
            if path.startswith("https://") or path.startswith("http://"):
                quote = "yes"
            else:
                quote = "no"
        safe_path = url_quote(path, safe=safe) if quote == "yes" else path
        return safe_path

    def _build_path(
        self,
        size: str,
        crop_start: Optional[str],
        crop_stop: Optional[str],
        fit: bool,
        stretch: bool,
        halign: Optional[str],
        valign: Optional[str],
        focal: Optional[str],
        quality: Optional[int],
        blur: Optional[float],
        round_corner: int | tuple[int, int] | tuple[int, int, int] | None = None,
        filters: list[str] | None = None,
    ) -> str:
        """
        Build the image path with the transformations applied.

        Args:
            size (str): The dimensions in 'widthxheight' format.
            crop_start (Optional[str]): The starting point for cropping.
            crop_stop (Optional[str]): The ending point for cropping.
            fit (bool): Whether to fit the image within the given dimensions.
            stretch (bool): Whether to stretch the image.
            halign (Optional[str]): Horizontal alignment ('left', 'center', 'right').
            valign (Optional[str]): Vertical alignment ('top', 'middle', 'bottom').
            focal (Optional[str]): Focal point for image (e.g. '0.1,0.8').
            quality (Optional[int]): Image quality (0 to 100).
            blur: Image blur (sigma).
            rounded_corder:  adds rounded corners to the image with the specified color as background
                             rx, ry amount of pixel to use as radius. ry = rx if ry is not provided
                            color the color name or hexadecimal rgb expression without the “#” character

        Returns:
            str: The constructed path for the image.
        """
        if filters is None:
            filters = []
        # path = [f"{size}"] if size else []
        path = []
        if crop_start and crop_stop:
            path.append(f"/{crop_start}:{crop_stop}")
        if fit:
            path.append("fit-in")
        if stretch:
            path.append("stretch")
        if size:
            path.append(f"{size}")
        if halign:
            path.append(f"{halign}")
        if valign:
            path.append(f"{valign}")
        if focal:
            filters.append(f"focal({focal})")
        if quality:
            filters.append(f"quality({quality})")
        if blur:
            filters.append(f"blur({blur})")
        if round_corner:
            rc = [round_corner] if isinstance(round_corner, int) else round_corner
            filters.append(f"round_corner({','.join([str(r) for r in rc])})")
        if filters:
            path.append(f"filters:{':'.join(filters)}")
        path.append(f"{url_quote(self.image_url.strip('/'))}")
        path = [p for p in path if p]
        return "/".join(path).strip("/")

    def transform(
        self,
        size: str = "600x400",
        crop_start: Optional[str] = None,
        crop_stop: Optional[str] = None,
        fit: bool = False,
        stretch: bool = False,
        halign: Optional[str] = None,
        valign: Optional[str] = None,
        focal: Optional[str] = None,
        quality: Optional[int] = None,
        blur: Optional[float] = None,
        round_corner: int | tuple[int, int] | tuple[int, int, int] | None = None,
        filters: list[str] | None = None,
        unsafe: bool = False,
    ) -> TransformedImage:
        """
        Apply transformations to the image and return a TransformedImage object.

        Args:
            size: The dimensions of the image in 'widthxheight' format.
            crop_start: The starting point for cropping.
            crop_stop: The ending point for cropping.
            fit: Whether to fit the image within the dimensions.
            stretch: Whether to stretch the image to fill the dimensions.
            halign: Horizontal alignment ('left', 'center', 'right').
            valign: Vertical alignment ('top', 'middle', 'bottom').
            focal: Focal point for image.
            quality: Image quality (0 to 100).
            blur: Image blur (sigma).
            unsafe: If True, the URL is not signed.
            filters: A list of filters to apply to the image.

        Returns:
            TransformedImage: A TransformedImage object with the transformed URL.
        """
        path = self._build_path(
            size=size,
            crop_start=crop_start,
            crop_stop=crop_stop,
            fit=fit,
            stretch=stretch,
            halign=halign,
            valign=valign,
            focal=focal,
            quality=quality,
            blur=blur,
            round_corner=round_corner,
            filters=filters,
        )
        # print(f"PATH: {path}")

        # Generate URL signature if unsafe is False
        signature = "unsafe"
        if not unsafe:
            if path.startswith("https://commons.wikimedia.org"):
                # this is needed because redirect do not work with imagor, return correct redirected image
                resp = requests.head(
                    path,
                    allow_redirects=True,
                    headers={
                        "User-Agent": "wodore-backend/1.0 (contact: info@wodo.re)"
                    },
                )  # follows redirect
                path = resp.url
            path = self.url_quote(path, quote="auto")
            signature = self.sign_path(path)

        # Full URL
        url = f"{settings.IMAGOR_URL}/{signature}/{path}"
        return TransformedImage(url)


if __name__ == "__main__":
    test_paths = [
        (
            "500x500/top/raw.githubusercontent.com/cshum/imagor/master/testdata/gopher.png",
            "cST4Ko5_FqwT3BDn-Wf4gO3RFSk=",
            "O9OXzhvQEZkxzMnOJ5BxH15RlS4=",
        ),
        (
            "https://static.suissealpine.sac-cas.ch/1537881166_827257329Mb.jpg",
            "zcyZsckdhXe1X0Kf5z-d09ZEdSg=",
            "DQxwyxRnYHqfaKxUBjIlvhPESj0=",
        ),
        (
            "https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/File%3ALoetschepasshuette.JPG&width=400",
            "X2AFmX2Ldm_-D-aIl6RqmQfZx9E=",
            "hiCdH20z8Kc-EZN9ZFOLPmCmvyo=",
        ),
    ]
    for test_path, expected_unsafe, expected_safe in test_paths:
        if test_path.startswith("https://commons.wikimedia.org"):
            print(f"Get redirect address for: '{test_path}'")
            resp = requests.head(
                test_path,
                allow_redirects=True,
                headers={"User-Agent": "wodore-backend/1.0 (contact: info@wodore.com)"},
            )  # follows redirect
            test_path = resp.url

        signed_url_unsafe = ImagorImage.sign_path(
            test_path, key="mysecret", algorithmus="sha1", quote=False
        )
        print(f"Path: {test_path}")
        print("   with unsafe (unescaped) URL:")
        print(f"     Signed:   {signed_url_unsafe}")
        print(f"     Expected: {expected_unsafe}")
        assert signed_url_unsafe == expected_unsafe
        signed_url_safe = ImagorImage.sign_path(
            test_path, key="mysecret", algorithmus="sha1", quote=True
        )
        safe_path = url_quote(test_path, safe="")
        print(f"   with safe (escaped) URL: '{safe_path}'")
        print(f"     Signed:   {signed_url_safe}")
        print(f"     Expected: {expected_safe}")
        assert signed_url_safe == expected_safe
    # console.log(sign('500x500/top/raw.githubusercontent.com/cshum/imagor/master/testdata/gopher.png', 'mysecret'))
    # // cST4Ko5_FqwT3BDn-Wf4gO3RFSk=/500x500/top/raw.githubusercontent.com/cshum/imagor/master/testdata/gopher.png
