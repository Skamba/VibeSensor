import { cloneTransportValue } from "./clone";

export function fromTransportPayload<TTransport, TLocal>(payload: TTransport): TLocal {
  return cloneTransportValue(payload) as unknown as TLocal;
}

export function toTransportPayload<TLocal, TTransport>(payload: TLocal): TTransport {
  return cloneTransportValue(payload) as unknown as TTransport;
}
