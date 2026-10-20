import { useRef, useState } from "react";
import { userFacingError } from "../utils/userFacingError";

/** Keep download state separate from import validation and business notices. */
export function useDownloadFeedback() {
  const inFlight = useRef(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [isError, setIsError] = useState(false);

  const run = async (download: () => Promise<void>, successMessage: string) => {
    // A ref also blocks a second click before React commits the disabled state.
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setMessage("");
    setIsError(false);
    try {
      await download();
      setMessage(successMessage);
    } catch (error) {
      setIsError(true);
      setMessage(`下载失败：${userFacingError(error, "请稍后重试。")}`);
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return { busy, message, isError, run };
}
