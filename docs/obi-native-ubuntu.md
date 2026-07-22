# Native Ubuntu OBI validation

The native Ubuntu VM is the authoritative environment for PARALLAX eBPF evidence. WSL2 can exercise the same verifier during development, but a WSL result is not accepted as final native-VM evidence.

## Host requirements

- Ubuntu Linux on an 8-vCPU, 32-GiB VM with at least 100 GiB of SSD storage.
- Kernel 5.8 or newer.
- Readable kernel BTF at `/sys/kernel/btf/vmlinux`.
- Native Docker Engine and Compose, not Docker Desktop integration.
- A mounted bpffs at `/sys/fs/bpf`.
- OBI v0.10.0 with the host PID namespace and the privileges declared in `infra/docker-compose.yaml`.

Verify the host before deployment:

```bash
uname -a
systemd-detect-virt
test -r /sys/kernel/btf/vmlinux
stat /sys/kernel/btf/vmlinux
sudo mountpoint /sys/fs/bpf || sudo mount -t bpf bpf /sys/fs/bpf
docker info
sudo capsh --print
sysctl kernel.unprivileged_bpf_disabled kernel.perf_event_paranoid kernel.kptr_restrict
```

To persist bpffs across boots, add this entry to `/etc/fstab` on the dedicated VM:

```text
bpf /sys/fs/bpf bpf defaults 0 0
```

The OBI container runs with `pid: host` and `privileged: true`. These permissions are necessary to attach eBPF probes to processes in the project's other containers. The discovery configuration additionally requires `containers_only: true` and internal port `8000`, so host processes are not selected. The VM must be dedicated to ORBITAL and must not host unrelated port-8000 containers.

Keep the ORBITAL Docker network private to the VM. Do not configure OBI with remote discovery targets, host-network scanning, or external OTLP destinations. The only OBI export destination is the project Collector at `http://otel-collector:4318`.

## Verification

After `make bootstrap`, run:

```bash
make verify-obi
```

The command starts the real OBI profile, executes the owned synthetic refund fixture, waits for ingestion, and queries the ClickHouse trace store used by SigNoz. It requires one trace to contain:

- the SDK-declared `store_credit` action;
- an OBI client/server connection to `/v1/refunds` with the same trace ID;
- the absence or presence of a correlated policy decision;
- an Ed25519 receipt whose digest, signature and public key came from stored telemetry;
- a resulting `CONTRADICTED` evidence claim and a SigNoz trace link.

Stopping OBI, removing its trace export, or making the sensor unavailable causes `make verify-obi` to exit non-zero. Sensor APIs return `UNKNOWN` rather than PASS whenever SigNoz, OBI, OPA, semantic spans, or signed-receipt evidence is unavailable.

OBI is configured by `collector/obi-config.yaml`. It observes only local containers on the dedicated ORBITAL VM; it must never be pointed at an external host or network.

References:

- <https://opentelemetry.io/docs/zero-code/obi/setup/docker/>
- <https://opentelemetry.io/docs/zero-code/obi/configure/service-discovery/>
- <https://opentelemetry.io/docs/zero-code/obi/configure/example/>
