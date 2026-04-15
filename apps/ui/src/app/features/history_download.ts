const DOWNLOAD_REVOKE_DELAY_MS = 1000;

export function filenameFromDisposition(headerValue: string | null, fallback: string): string {
  if (!headerValue) {
    return fallback;
  }
  const utf8Match = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      /* fall through to simple match */
    }
  }
  const simpleMatch = headerValue.match(/filename="?([^";]+)"?/i);
  if (simpleMatch?.[1]) {
    return simpleMatch[1];
  }
  return fallback;
}

export async function downloadBlobFile(url: string, fallbackName: string): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (payload && typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch (_err) {
      /* ignore */
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const fileName = filenameFromDisposition(
    response.headers.get("content-disposition"),
    fallbackName || "download.bin",
  );
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), DOWNLOAD_REVOKE_DELAY_MS);
}
