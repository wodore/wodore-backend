import base64
import hashlib
import hmac
import os
from typing import Optional
from urllib.parse import quote

from django.conf import settings
from django.db.models.fields.files import ImageFieldFile
from django.utils.html import format_html

# https://github.com/cshum/imagor

# Load environment variables for Imagor configurations


class TransformedImage:
    """Represents a transformed image with its URL and helper methods."""

    def __init__(self, image: ImageFieldFile, url: str) -> None:
        """
        Initialize the TransformedImage class.

        Args:
            image (ImageFieldFile): The Django ImageFieldFile object.
            url (str): The URL of the transformed image.
        """
        self.image = image
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

    def __init__(self, image: ImageFieldFile) -> None:
        """
        Initialize the ImagorImage class with a Django Image object.

        Args:
            image (ImageFieldFile): The Django ImageFieldFile object.
        """
        self.image = image

    @classmethod
    def sign_path(cls, path: str, key: str | None = None) -> str:
        """
        Generate a HMAC-SHA256 signature for the path and return it in Base64.

        Args:
            path (str): The image URL path to sign.

        Returns:
            str: The signed path.
        """
        imagor_key = key or settings.IMAGOR_KEY
        print(f"IMAGOR KEY: {key}")
        # hmac_digest = hmac.new(IMAGOR_SECRET.encode("utf-8"), path.encode("utf-8"), hashlib.sha256).digest()
        hmac_digest = hmac.new(imagor_key.encode("utf-8"), path.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(hmac_digest).decode("utf-8")  # .rstrip("=")
        # return signature.replace("+", "-").replace("/", "_")

    # function signPath(path: string, secret: string) {
    #   return hmacSHA256(path, secret)
    #     .toString(Base64)
    #     .replace(/\+/g, '-')
    #     .replace(/\//g, '_');
    # }
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
            rounded_corder:  adds rounded corners to the image with the specified color as background
                             rx, ry amount of pixel to use as radius. ry = rx if ry is not provided
                            color the color name or hexadecimal rgb expression without the “#” character

        Returns:
            str: The constructed path for the image.
        """
        if filters is None:
            filters = []
        path = [f"{size}"] if size else []
        if crop_start and crop_stop:
            path += f"/{crop_start}:{crop_stop}"
        if fit:
            path.append("fit-in")
        if stretch:
            path.append("stretch")
        if halign:
            path.append(f"{halign}")
        if valign:
            path.append(f"{valign}")
        if focal:
            filters.append(f"focal({focal})")
        if quality:
            filters.append(f"quality({quality})")
        if round_corner:
            rc = [round_corner] if isinstance(round_corner, int) else round_corner
            filters.append(f"round_corner({','.join([str(r) for r in rc])})")
        if filters:
            path.append(f"filters:{':'.join(filters)}")
        path.append(f"{quote(self.image.url.strip('/'))}")
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
        round_corner: int | tuple[int, int] | tuple[int, int, int] | None = None,
        filters: list[str] | None = None,
        unsafe: bool = False,
    ) -> TransformedImage:
        """
        Apply transformations to the image and return a TransformedImage object.

        Args:
            size (str): The dimensions of the image in 'widthxheight' format.
            crop_start (Optional[str]): The starting point for cropping.
            crop_stop (Optional[str]): The ending point for cropping.
            fit (bool): Whether to fit the image within the dimensions.
            stretch (bool): Whether to stretch the image to fill the dimensions.
            halign (Optional[str]): Horizontal alignment ('left', 'center', 'right').
            valign (Optional[str]): Vertical alignment ('top', 'middle', 'bottom').
            focal (Optional[str]): Focal point for image.
            quality (Optional[int]): Image quality (0 to 100).
            unsafe (bool): If True, the URL is not signed.

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
            round_corner=round_corner,
            filters=filters,
        )
        print(f"PATH: {path}")

        # Generate URL signature if unsafe is False
        signature = "unsafe"
        if not unsafe:
            signature = self.sign_path(path)

        # Full URL
        url = f"{settings.IMAGOR_URL}/{signature}/{path}"
        return TransformedImage(self.image, url)


if __name__ == "__main__":
    test_path = "500x500/top/raw.githubusercontent.com/cshum/imagor/master/testdata/gopher.png"
    signed = ImagorImage.sign_path(test_path, key="mysecret")
    expected = "cST4Ko5_FqwT3BDn-Wf4gO3RFSk="
    print(f"Signed:   {signed}")
    print(f"Expected: {expected}")
    assert signed == expected
    # console.log(sign('500x500/top/raw.githubusercontent.com/cshum/imagor/master/testdata/gopher.png', 'mysecret'))
    # // cST4Ko5_FqwT3BDn-Wf4gO3RFSk=/500x500/top/raw.githubusercontent.com/cshum/imagor/master/testdata/gopher.png
