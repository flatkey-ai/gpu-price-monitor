> ## Documentation Index
> Fetch the complete documentation index at: https://docs.nebius.com/llms.txt
> Use this file to discover all available pages before exploring further.

# Nebius AI Cloud regions

Each Nebius AI Cloud resource, such as a virtual machine or a Managed Service for Kubernetes® cluster, is hosted in a *Nebius AI Cloud region*: the geographical location of the underlying physical infrastructure.

## Public regions

Public regions are available to all Nebius users:

* `eu-north1`: Finland
* `eu-south1`: Madrid, Spain
* `eu-west1`: France&#x20;
* `eu-west2`: France&#x20;
* `me-west1`: Israel
* `us-central1`: Kansas City, Missouri, US
* `us-north1`: Woodbury, Minnesota, US
* `uk-south1`: United Kingdom
* `uk-south2`: United Kingdom&#x20;

## Private regions

The `eu-north2` region is available only to the users who already have deployments there.

* `eu-north2`: Iceland

## Availability of services per region

The availability of services depends on the region of the project where you work. Nebius AI Cloud provides you with a project per region when you [sign up](https://docs.nebius.com/signup-billing/sign-up.md).

| Service | `eu-north1` | `eu-west1` | `me-west1` | `us-central1` | `uk-south1` | `uk-south2` | `eu-north2` | `eu-south1` | `eu-west2` | `us-north1` |
| - | - | - | - | - | - | - | - | - | - | - |
| [Compute](https://docs.nebius.com/compute/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Managed Service for Soperator](https://docs.nebius.com/slurm-soperator/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ | — |
| [Managed Service for Kubernetes®](https://docs.nebius.com/kubernetes/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Serverless AI](https://docs.nebius.com/serverless/overview.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| [Object Storage](https://docs.nebius.com/object-storage/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Managed Service for PostgreSQL®](https://docs.nebius.com/postgresql/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | — | — | — | ✓ | — |
| [Container Registry](https://docs.nebius.com/container-registry/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Managed Service for MLflow](https://docs.nebius.com/mlflow/index.md) | ✓ | — | ✓ | ✓ | ✓ | — | — | — | ✓ | — |
| [Applications](https://docs.nebius.com/applications/index.md) | ✓ | — | — | ✓ | — | — | — | — | — | — |
| [Monitoring](https://docs.nebius.com/observability/monitoring.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Logging](https://docs.nebius.com/observability/logging.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Virtual Networks](https://docs.nebius.com/vpc/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Nebius Tunnels](https://docs.nebius.com/tunnels/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Identity and Access Management](https://docs.nebius.com/iam/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Audit Logs](https://docs.nebius.com/audit-logs/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [Key Management Service](https://docs.nebius.com/kms/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| [SecretStash](https://docs.nebius.com/mysterybox/index.md) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

> [!NOTE]
>
> If a service is not available in the required region, you can [contact technical support](https://console.nebius.com/support/create-ticket) and send a request to add the service to the region.

## Availability of platforms per region

The availability of platforms depends on the region of the project where you work.
You can [get a list](https://docs.nebius.com/compute/virtual-machines/list-platforms.md) of platforms and presets supported in a given project.

| Platform name | `eu-north1` | `eu-west1` | `me-west1` | `us-central1` | `uk-south1` | `uk-south2` | `eu-north2` | `eu-south1` | `eu-west2` | `us-north1` |
| - | - | - | - | - | - | - | - | - | - | - |
| NVIDIA® B300 NVLink | — | — | — | — | ✓ | — | — | — | ✓ | ✓ |
| NVIDIA® B200 NVLink | — | — | ✓ | ✓ | — | — | — | — | — | — |
| NVIDIA® H200 NVLink | ✓ | ✓ | — | ✓ | — | — | ✓ | — | — | — |
| NVIDIA® H100 NVLink | ✓ | — | — | — | — | — | — | — | — | — |
| NVIDIA® RTX PRO 6000 | — | — | — | ✓ | — | ✓ | — | ✓ | — | — |
| NVIDIA® L40S Intel | ✓ | — | — | — | — | — | — | — | — | — |
| NVIDIA® L40S AMD | ✓ | — | — | — | — | — | — | — | — | — |
| Non-GPU AMD EPYC Genoa | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Non-GPU Intel Ice Lake | ✓ | — | — | — | — | — | — | — | — | — |

***

*Postgres, PostgreSQL and the Slonik Logo are trademarks or registered trademarks of the PostgreSQL Community Association of Canada, and used with their permission.*
