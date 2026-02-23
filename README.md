# Arista cEOS + Containerlab + AVD (5.7.x)

This lab deploys a DC1 fabric in containerlab (cEOS) with two Linux hosts (`server1`, `server2`), then builds and deploys the configuration using Arista AVD.

The data model is based on the AVD reference design **Single Data Center - L3LS** (`releases/v5.7.x`) and intentionally:

- does not include CloudVision deployment (`cv_deploy`),
- does not include `dc1-leaf1c` or `dc1-leaf2c`.

## 1) Requirements

- Docker
- containerlab
- Python 3.10+
- Ansible Core 2.15+

## 2) Install AVD dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip "ansible-core>=2.15,<2.18"
ansible-galaxy collection install -r requirements.yml
```

`requirements.yml` is pinned to AVD `5.7.x` using `>=5.7.0,<5.8.0`.

## 3) Deploy containerlab topology

```bash
sudo containerlab deploy -t lab.clab.yml
```

Verify:

```bash
containerlab inspect -t lab.clab.yml
```

## 4) Run separate AVD playbooks

```bash
ansible-playbook playbooks/01_build_structured_configs.yml
ansible-playbook playbooks/02_build_device_cli.yml
ansible-playbook playbooks/03_deploy_configs.yml
ansible-playbook playbooks/04_validate_fabric.yml
```

AVD output is generated in `build/`:

- `build/structured_configs/`
- `build/intended/configs/`
- `build/documentation/`

## 5) Interface naming continuity and mapping

Interface naming is kept consistent between containerlab and AVD:

- containerlab `eth1` / `eth2` on leafs maps to AVD `Ethernet1` / `Ethernet2` (`uplink_interfaces`) toward `dc1-spine1` / `dc1-spine2` (`uplink_switches`),
- containerlab `eth3` / `eth4` on each MLAG pair maps to AVD `Ethernet3` / `Ethernet4` (`mlag_interfaces`),
- containerlab `eth5` on leafs maps to AVD `Ethernet5` for host-facing ports.

Connected endpoints are mapped 1:1 to all server links in `lab.clab.yml`:

- `server1:eth1` ↔ `dc1-leaf1a:Ethernet5`,
- `server1:eth2` ↔ `dc1-leaf1b:Ethernet5`,
- `server2:eth1` ↔ `dc1-leaf2a:Ethernet5`,
- `server2:eth2` ↔ `dc1-leaf2b:Ethernet5`.

## 6) Quick endpoint checks

After deployment, verify interfaces inside host containers:

```bash
docker exec -it clab-dc1_fabric-server1 ip addr
docker exec -it clab-dc1_fabric-server2 ip addr
```

## 7) Destroy lab

```bash
sudo containerlab destroy -t lab.clab.yml
```

---

## AVD reference

- Repo: https://github.com/aristanetworks/avd
- Branch line: `releases/v5.7.x`

This repository uses `arista.avd` collection version line `5.7.x` compatible with that branch.
