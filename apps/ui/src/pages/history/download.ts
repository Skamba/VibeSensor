const REVOKE_DELAY_MS = 1000;

/** The file name from a Content-Disposition header, else `fallback`. */
export function filenameFromDisposition(
  header: string | null,
  fallback: string,
): string {
  const encoded = header?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      // Fall through to the plain filename.
    }
  }
  return header?.match(/filename="?([^";]+)"?/i)?.[1] ?? fallback;
}

/** Fetches `url` and saves the body as a file (binary, so not via apiJson). */
export async function downloadFile(
  url: string,
  fallbackName: string,
): Promise<void> {
  const response = await fetch(url);
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // Keep the status text.
    }
    throw new Error(detail);
  }
  const objectUrl = URL.createObjectURL(await response.blob());
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filenameFromDisposition(
    response.headers.get("content-disposition"),
    fallbackName,
  );
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(objectUrl), REVOKE_DELAY_MS);
}
