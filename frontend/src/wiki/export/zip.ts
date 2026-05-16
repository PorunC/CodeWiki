export type ZipEntry = {
  path: string;
  data: string | Uint8Array;
};

const UTF8_FLAG = 0x0800;

export function buildStoredZip(entries: ZipEntry[]): Uint8Array {
  const encoder = new TextEncoder();
  const localRecords: Uint8Array[] = [];
  const centralRecords: Uint8Array[] = [];
  let offset = 0;

  for (const entry of entries) {
    const pathBytes = encoder.encode(entry.path);
    const dataBytes = typeof entry.data === "string" ? encoder.encode(entry.data) : entry.data;
    const checksum = crc32(dataBytes);
    const { date, time } = dosTimestamp(new Date());
    const localHeader = concatBytes(
      uint32(0x04034b50),
      uint16(20),
      uint16(UTF8_FLAG),
      uint16(0),
      uint16(time),
      uint16(date),
      uint32(checksum),
      uint32(dataBytes.length),
      uint32(dataBytes.length),
      uint16(pathBytes.length),
      uint16(0),
      pathBytes,
      dataBytes
    );
    localRecords.push(localHeader);

    centralRecords.push(
      concatBytes(
        uint32(0x02014b50),
        uint16(20),
        uint16(20),
        uint16(UTF8_FLAG),
        uint16(0),
        uint16(time),
        uint16(date),
        uint32(checksum),
        uint32(dataBytes.length),
        uint32(dataBytes.length),
        uint16(pathBytes.length),
        uint16(0),
        uint16(0),
        uint16(0),
        uint16(0),
        uint32(0),
        uint32(offset),
        pathBytes
      )
    );
    offset += localHeader.length;
  }

  const centralDirectory = concatBytes(...centralRecords);
  return concatBytes(
    ...localRecords,
    centralDirectory,
    uint32(0x06054b50),
    uint16(0),
    uint16(0),
    uint16(entries.length),
    uint16(entries.length),
    uint32(centralDirectory.length),
    uint32(offset),
    uint16(0)
  );
}

function crc32(bytes: Uint8Array): number {
  let crc = 0xffffffff;
  for (const byte of bytes) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      const mask = -(crc & 1);
      crc = (crc >>> 1) ^ (0xedb88320 & mask);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosTimestamp(value: Date): { date: number; time: number } {
  const year = Math.max(value.getFullYear(), 1980);
  return {
    date: ((year - 1980) << 9) | ((value.getMonth() + 1) << 5) | value.getDate(),
    time: (value.getHours() << 11) | (value.getMinutes() << 5) | Math.floor(value.getSeconds() / 2)
  };
}

function concatBytes(...chunks: Uint8Array[]): Uint8Array {
  const totalLength = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const result = new Uint8Array(totalLength);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.length;
  }
  return result;
}

function uint16(value: number): Uint8Array {
  const bytes = new Uint8Array(2);
  new DataView(bytes.buffer).setUint16(0, value, true);
  return bytes;
}

function uint32(value: number): Uint8Array {
  const bytes = new Uint8Array(4);
  new DataView(bytes.buffer).setUint32(0, value, true);
  return bytes;
}
