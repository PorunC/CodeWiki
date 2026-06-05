export type ReleaseVersionInput = {
  packageName?: string;
  packageVersion: string;
  refType?: string;
  refName?: string;
  requestedVersion?: string;
};

export type ReleaseVersionCheck = {
  source: string;
  version: string;
};

export type ReleaseVersionResult = {
  verified: true;
  packageName?: string;
  packageVersion: string;
  message: string;
};

export declare function verifyReleaseVersion(
  input: ReleaseVersionInput,
): ReleaseVersionResult;

export declare function releaseVersionChecks(
  input: Pick<ReleaseVersionInput, "refType" | "refName" | "requestedVersion">,
): ReleaseVersionCheck[];
