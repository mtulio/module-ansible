#!/usr/bin/python
# Copyright: Ansible Project
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
import copy
import yaml
import re
import traceback

from uuid import UUID

HAS_SDK = True

try:
    import ionoscloud
    from ionoscloud import __version__ as sdk_version
    from ionoscloud.models import Volume, VolumeProperties
    from ionoscloud.rest import ApiException
    from ionoscloud import ApiClient
except ImportError:
    HAS_SDK = False

from ansible import __version__
from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible.module_utils.six.moves import xrange
from ansible.module_utils._text import to_native


__metaclass__ = type

ANSIBLE_METADATA = {
    'metadata_version': '1.1',
    'status': ['preview'],
    'supported_by': 'community',
}
USER_AGENT = 'ansible-module/%s_ionos-cloud-sdk-python/%s' % ( __version__, sdk_version)
DOC_DIRECTORY = 'compute-engine'
STATES = ['present', 'absent', 'update']
OBJECT_NAME = 'Volume'

OPTIONS = {
    'datacenter': {
        'description': ['The datacenter in which to create the volumes.'],
        'available': STATES,
        'required': STATES,
        'type': 'str',
    },
    'server': {
        'description': ['The server to which to attach the volume.'],
        'available': ['present'],
        'type': 'str',
    },
    'name': {
        'description': ['The name of the volumes. Names are enumerated if count > 1.'],
        'required': ['present'],
        'available': STATES,
        'type': 'str',
    },
    'size': {
        'description': ['The size of the volume.'],
        'available': ['update', 'present'],
        'default': 10,
        'type': 'int',
    },
    'bus': {
        'description': ['The bus type.'],
        'choices': ['VIRTIO', 'IDE'],
        'default': 'VIRTIO',
        'available': ['present', 'update'],
        'type': 'str',
    },
    'image': {
        'description': ['The image alias or ID for the volume. This can also be a snapshot image ID.'],
        'available': ['present'],
        'type': 'str',
    },
    'image_password': {
        'description': ['Password set for the administrative user.'],
        'available': ['present'],
        'type': 'str',
        'no_log': True,
        'version_added': '2.2',
    },
    'ssh_keys': {
        'description': ['Public SSH keys allowing access to the virtual machine.'],
        'available': ['present'],
        'type': 'list',
        'default': [],
        'version_added': '2.2',
    },
    'disk_type': {
        'description': ['The disk type of the volume.'],
        'choices': ['HDD', 'SSD', 'SSD Premium', 'SSD Standard'],
        'default': 'HDD',
        'available': ['present'],
        'type': 'str',
    },
    'licence_type': {
        'description': ['The licence type for the volume. This is used when the image is non-standard.'],
        'choices': ['LINUX', 'WINDOWS', 'UNKNOWN', 'OTHER', 'WINDOWS2016'],
        'default': 'UNKNOWN',
        'available': ['present'],
        'type': 'str',
    },
    'availability_zone': {
        'description': ['The storage availability zone assigned to the volume.'],
        'choices': ['AUTO', 'ZONE_1', 'ZONE_2', 'ZONE_3'],
        'available': ['present', 'update'],
        'type': 'str',
        'version_added': '2.3',
    },
    'count': {
        'description': ['The number of volumes you wish to create.'],
        'available': ['present'],
        'default': 1,
        'type': 'int',
    },
    'instance_ids': {
        'description': ["list of instance ids. Should only contain one ID if renaming in update state"],
        'available': ['absent', 'update'],
        'default': [],
        'type': 'list',
    },
    'backupunit_id': {
        'description': [
            "The ID of the backup unit that the user has access to. The property is immutable and is only "
            "allowed to be set on creation of a new a volume. It is mandatory to provide either 'public image' or 'imageAlias' "
            "in conjunction with this property.",
        ],
        'available': ['present'],
        'type': 'str',
    },
    'user_data': {
        'description': [
            "The cloud-init configuration for the volume as base64 encoded string. The property is immutable "
            "and is only allowed to be set on creation of a new a volume. It is mandatory to provide either 'public image' "
            "or 'imageAlias' that has cloud-init compatibility in conjunction with this property.",
        ],
        'available': ['present'],
        'type': 'str',
    },
    'cpu_hot_plug': {
        'description': ['Hot-plug capable CPU (no reboot required).'],
        'available': ['present', 'update'],
        'type': 'bool',
    },
    'ram_hot_plug': {
        'description': ['Hot-plug capable RAM (no reboot required)'],
        'available': ['present', 'update'],
        'type': 'bool',
    },
    'nic_hot_plug': {
        'description': ['Hot-plug capable NIC (no reboot required).'],
        'available': ['present', 'update'],
        'type': 'bool',
    },
    'nic_hot_unplug': {
        'description': ['Hot-unplug capable NIC (no reboot required)'],
        'available': ['present', 'update'],
        'type': 'bool',
    },
    'disc_virtio_hot_plug': {
        'description': ['Hot-plug capable Virt-IO drive (no reboot required).'],
        'available': ['present', 'update'],
        'type': 'bool',
    },
    'disc_virtio_hot_unplug': {
        'description': ['Hot-unplug capable Virt-IO drive (no reboot required). Not supported with Windows VMs.'],
        'available': ['present', 'update'],
        'type': 'bool',
    },
    'api_url': {
        'description': ['The Ionos API base URL.'],
        'version_added': '2.4',
        'env_fallback': 'IONOS_API_URL',
        'available': STATES,
        'type': 'str',
    },
    'username': {
        # Required if no token, checked manually
        'description': ['The Ionos username. Overrides the IONOS_USERNAME environment variable.'],
        'aliases': ['subscription_user'],
        'env_fallback': 'IONOS_USERNAME',
        'available': STATES,
        'type': 'str',
    },
    'password': {
        # Required if no token, checked manually
        'description': ['The Ionos password. Overrides the IONOS_PASSWORD environment variable.'],
        'aliases': ['subscription_password'],
        'available': STATES,
        'no_log': True,
        'env_fallback': 'IONOS_PASSWORD',
        'type': 'str',
    },
    'token': {
        # If provided, then username and password no longer required
        'description': ['The Ionos token. Overrides the IONOS_TOKEN environment variable.'],
        'available': STATES,
        'no_log': True,
        'env_fallback': 'IONOS_TOKEN',
        'type': 'str',
    },
    'wait': {
        'description': ['Wait for the resource to be created before returning.'],
        'default': True,
        'available': STATES,
        'choices': [True, False],
        'type': 'bool',
    },
    'wait_timeout': {
        'description': ['How long before wait gives up, in seconds.'],
        'default': 600,
        'available': STATES,
        'type': 'int',
    },
    'state': {
        'description': ['Indicate desired state of the resource.'],
        'default': 'present',
        'choices': STATES,
        'available': STATES,
        'type': 'str',
    },
}

def transform_for_documentation(val):
    val['required'] = len(val.get('required', [])) == len(STATES) 
    del val['available']
    del val['type']
    return val

DOCUMENTATION = '''
---
module: volume
short_description: Create, update or destroy a volume.
description:
     - Allows you to create, update or remove a volume from a Ionos datacenter.
version_added: "2.0"
options:
''' + '  ' + yaml.dump(yaml.safe_load(str({k: transform_for_documentation(v) for k, v in copy.deepcopy(OPTIONS).items()})), default_flow_style=False).replace('\n', '\n  ') + '''
requirements:
    - "python >= 2.6"
    - "ionoscloud >= 6.0.2"
author:
    - "IONOS Cloud SDK Team <sdk-tooling@ionos.com>"
'''

EXAMPLE_PER_STATE = {
  'present' : '''# Create Multiple Volumes
  - volume:
    datacenter: Tardis One
    name: vol%02d
    count: 5
    wait_timeout: 500
    state: present
  ''',
  'update' : '''# Update Volumes - only one ID if renaming
  - volume:
    name: 'new_vol_name'
    datacenter: Tardis One
    instance_ids: 'vol01'
    size: 50
    bus: IDE
    wait_timeout: 500
    state: update
  ''',
  'absent' : '''# Remove Volumes
  - volume:
    datacenter: Tardis One
    instance_ids:
      - 'vol01'
      - 'vol02'
    wait_timeout: 500
    state: absent
  ''',
}

EXAMPLES = '\n'.join(EXAMPLE_PER_STATE.values())

uuid_match = re.compile('[\w]{8}-[\w]{4}-[\w]{4}-[\w]{4}-[\w]{12}', re.I)


def _get_matched_resources(resource_list, identity, identity_paths=None):
    """
    Fetch and return a resource based on an identity supplied for it, if none or more than one matches
    are found an error is printed and None is returned.
    """

    if identity_paths is None:
        identity_paths = [['id'], ['properties', 'name']]

    def check_identity_method(resource):
        resource_identity = []

        for identity_path in identity_paths:
            current = resource
            for el in identity_path:
                current = getattr(current, el)
            resource_identity.append(current)

        return identity in resource_identity

    return list(filter(check_identity_method, resource_list.items))


def get_resource(module, resource_list, identity, identity_paths=None):
    matched_resources = _get_matched_resources(resource_list, identity, identity_paths)

    if len(matched_resources) == 1:
        return matched_resources[0]
    elif len(matched_resources) > 1:
        module.fail_json(msg="found more resources of type {} for '{}'".format(resource_list.id, identity))
    else:
        return None


def get_resource_id(module, resource_list, identity, identity_paths=None):
    resource = get_resource(module, resource_list, identity, identity_paths)
    return resource.id if resource is not None else None


def _get_request_id(headers):
    match = re.search('/requests/([-A-Fa-f0-9]+)/', headers)
    if match:
        return match.group(1)
    else:
        raise Exception("Failed to extract request ID from response "
                        "header 'location': '{location}'".format(location=headers['location']))


def _create_volume(module, volume_server, datacenter, name, client):
    size = module.params.get('size')
    bus = module.params.get('bus')
    image = module.params.get('image')
    image_password = module.params.get('image_password')
    ssh_keys = module.params.get('ssh_keys')
    disk_type = module.params.get('disk_type')
    availability_zone = module.params.get('availability_zone')
    licence_type = module.params.get('licence_type')
    cpu_hot_plug = module.params.get('cpu_hot_plug')
    ram_hot_plug = module.params.get('ram_hot_plug')
    nic_hot_plug = module.params.get('nic_hot_plug')
    nic_hot_unplug = module.params.get('nic_hot_unplug')
    disc_virtio_hot_plug = module.params.get('disc_virtio_hot_plug')
    disc_virtio_hot_unplug = module.params.get('disc_virtio_hot_unplug')
    backupunit_id = module.params.get('backupunit_id')
    user_data = module.params.get('user_data')
    wait_timeout = module.params.get('wait_timeout')
    wait = module.params.get('wait')

    if module.check_mode:
        module.exit_json(changed=True)

    try:
        volume_properties = VolumeProperties(name=name, type=disk_type, size=size, availability_zone=availability_zone,
                                             image_password=image_password, ssh_keys=ssh_keys,
                                             bus=bus,
                                             licence_type=licence_type, cpu_hot_plug=cpu_hot_plug,
                                             ram_hot_plug=ram_hot_plug, nic_hot_plug=nic_hot_plug,
                                             nic_hot_unplug=nic_hot_unplug, disc_virtio_hot_plug=disc_virtio_hot_plug,
                                             disc_virtio_hot_unplug=disc_virtio_hot_unplug, backupunit_id=backupunit_id,
                                             user_data=user_data)
        if image:
            if uuid_match.match(image):
                volume_properties.image = image
            else:
                volume_properties.image_alias = image

        volume = Volume(properties=volume_properties)

        response = volume_server.datacenters_volumes_post_with_http_info(datacenter_id=datacenter, volume=volume)
        (volume_response, _, headers) = response

        if wait:
            request_id = _get_request_id(headers['Location'])
            client.wait_for_completion(request_id=request_id, timeout=wait_timeout)

        return volume_response

    except Exception as e:
        module.fail_json(msg="failed to create the volume: %s" % to_native(e))


def _update_volume(module, volume_server, api_client, datacenter, volume):
    name = module.params.get('name')
    size = module.params.get('size')
    bus = module.params.get('bus')
    availability_zone = module.params.get('availability_zone')
    cpu_hot_plug = module.params.get('cpu_hot_plug')
    ram_hot_plug = module.params.get('ram_hot_plug')
    nic_hot_plug = module.params.get('nic_hot_plug')
    nic_hot_unplug = module.params.get('nic_hot_unplug')
    disc_virtio_hot_plug = module.params.get('disc_virtio_hot_plug')
    disc_virtio_hot_unplug = module.params.get('disc_virtio_hot_unplug')

    wait_timeout = module.params.get('wait_timeout')
    wait = module.params.get('wait')

    if module.check_mode:
        module.exit_json(changed=True)

    try:
        volume_properties = VolumeProperties(name=name if name is not None else volume.name, size=size,
                                             availability_zone=availability_zone, bus=bus, cpu_hot_plug=cpu_hot_plug,
                                             ram_hot_plug=ram_hot_plug, nic_hot_plug=nic_hot_plug,
                                             nic_hot_unplug=nic_hot_unplug, disc_virtio_hot_plug=disc_virtio_hot_plug,
                                             disc_virtio_hot_unplug=disc_virtio_hot_unplug)
        volume = Volume(properties=volume_properties)
        response = volume_server.datacenters_volumes_put_with_http_info(
            datacenter_id=datacenter,
            volume_id=volume.id,
            volume=volume
        )
        (volume_response, _, headers) = response
        if wait:
            request_id = _get_request_id(headers['Location'])
            api_client.wait_for_completion(request_id=request_id, timeout=wait_timeout)
        return volume_response

    except Exception as e:
        module.fail_json(msg="failed to update the volume: %s" % to_native(e))


def _delete_volume(module, volume_server, datacenter, volume):
    if module.check_mode:
        module.exit_json(changed=True)
    try:
        volume_server.datacenters_volumes_delete(datacenter, volume)
    except Exception as e:
        module.fail_json(msg="failed to remove the volume: %s" % to_native(e))


def create_volume(module, client):
    """
    Create volumes.

    This will create one or more volumes in a datacenter.

    module : AnsibleModule object
    client: authenticated ionoscloud object.

    Returns:
        dict of created volumes
    """
    datacenter = module.params.get('datacenter')
    name = module.params.get('name')
    count = module.params.get('count')

    volume_server = ionoscloud.VolumesApi(client)
    datacenter_server = ionoscloud.DataCentersApi(client)
    servers_server = ionoscloud.ServersApi(client)

    datacenter_list = datacenter_server.datacenters_get(depth=1)
    datacenter_id = get_resource_id(module, datacenter_list, datacenter)

    if datacenter_id is None:
        module.fail_json(msg='datacenter could not be found.')

    # Provide unique names by appending an auto incremented value at end of name
    if count > 1:
        numbers = set()
        count_offset = 1

        try:
            name % 0
        except TypeError as e:
            if (hasattr(e, 'message') and e.message.startswith('not all') or to_native(e).startswith('not all')):
                name = '%s%%d' % name
            else:
                module.fail_json(msg=e.message, exception=traceback.format_exc())

        number_range = xrange(count_offset, count_offset + count + len(numbers))
        available_numbers = list(set(number_range).difference(numbers))
        names = []
        numbers_to_use = available_numbers[:count]
        for number in numbers_to_use:
            names.append(name % number)
    else:
        names = [name]

    # Prefetch a list of volumes for later comparison.
    volume_list = volume_server.datacenters_volumes_get(datacenter_id, depth=1)

    volumes = []
    instance_ids = []

    changed = False
    for name in names:
        existing_volume_id = get_resource_id(module, volume_list, name)
        if existing_volume_id is not None:
            create_response = volume_server.datacenters_volumes_find_by_id(datacenter_id, existing_volume_id, depth=1)
            instance_ids.append(existing_volume_id)
            _attach_volume(module, servers_server, datacenter_id, existing_volume_id)
        else:
            create_response = _create_volume(module, volume_server, str(datacenter_id), name, client)
            instance_ids.append(create_response.id)
            _attach_volume(module, servers_server, datacenter_id, create_response.id)
            changed = True
        volumes.append(create_response)

    results = {
        'changed': changed,
        'failed': False,
        'volumes': [v.to_dict() for v in volumes],
        'action': 'create',
        'instance_ids': instance_ids
    }

    return results


def update_volume(module, client):
    """
    Update volumes.

    This will update one or more volumes in a datacenter.

    module : AnsibleModule object
    client: authenticated ionoscloud object.

    Returns:
        updated volume
    """
    datacenter = module.params.get('datacenter')
    instance_ids = module.params.get('instance_ids')
    name = module.params.get('name')

    volume_server = ionoscloud.VolumesApi(client)
    datacenter_server = ionoscloud.DataCentersApi(client)

    if name is None:
        if not isinstance(instance_ids, list) or len(instance_ids) < 1:
            module.fail_json(msg='instance_ids should be a list of volume ids or names, aborting')
    else:
        if isinstance(instance_ids, list) and len(instance_ids) > 1:
            module.fail_json(msg='when renaming, instance_ids can only have one id at most')

    changed = False

    datacenter_list = datacenter_server.datacenters_get(depth=2)
    datacenter_id = get_resource_id(module, datacenter_list, datacenter)
    if datacenter_id is None:
        module.fail_json(msg='datacenter could not be found.')

    volume_list = volume_server.datacenters_volumes_get(datacenter_id, depth=1)

    # Fail early if one of the ids provided doesn't match any volume
    checked_instances = []
    for instance in instance_ids:
        volume = get_resource(module, volume_list, instance)
        if volume is None:
            module.fail_json(msg='Volume \'%s\' not found.' % str(instance))
        checked_instances.append(volume)

    updated_volumes = []
    for instance in checked_instances:
        existing_volume_by_name = None if name is None else get_resource_id(module, volume_list, name)
        if existing_volume_by_name is not None:
            module.fail_json(msg='A volume with the name %s already exists.' % name)

        volume = get_resource(module, volume_list, instance)
        if volume is not None:
            update_response = _update_volume(module, volume_server, client, datacenter_id, volume)
            changed = True
            updated_volumes.append(update_response)

    results = {
        'changed': changed,
        'failed': False,
        'volume': [v.to_dict() for v in updated_volumes],
        'action': 'update'
    }

    return results


def delete_volume(module, client):
    """
    Remove volumes.

    This will remove one or more volumes from a datacenter.

    module : AnsibleModule object
    client: authenticated ionoscloud object.

    Returns:
        True if the volumes were removed, false otherwise
    """

    volume_server = ionoscloud.VolumesApi(client)
    datacenter_server = ionoscloud.DataCentersApi(client)

    if not isinstance(module.params.get('instance_ids'), list) or len(module.params.get('instance_ids')) < 1:
        module.fail_json(msg='instance_ids should be a list of volume ids or names, aborting')

    datacenter = module.params.get('datacenter')
    instance_ids = module.params.get('instance_ids')

    # Locate UUID for Datacenter
    datacenter_list = datacenter_server.datacenters_get(depth=2)
    datacenter_id = get_resource_id(module, datacenter_list, datacenter)

    volumes = volume_server.datacenters_volumes_get(datacenter_id, depth=1)

    changed = False
    volume_id = None
    for n in instance_ids:
        volume_id = get_resource_id(module, volumes, n)
        if volume_id is not None:
            _delete_volume(module, volume_server, datacenter_id, volume_id)
            changed = True

    return {
        'action': 'delete',
        'changed': changed,
        'id': volume_id
    }


def _attach_volume(module, server_client, datacenter, volume_id):
    """
    Attaches a volume.

    This will attach a volume to the server.

    module : AnsibleModule object
    client: authenticated ionoscloud object.

    Returns:
        the volume instance being attached
    """
    server = module.params.get('server')

    # Locate UUID for Server
    if server:
        server_list = server_client.datacenters_servers_get(datacenter_id=datacenter, depth=1)
        server_id = get_resource_id(module, server_list, server)

        try:
            volume = Volume(id=volume_id)
            return server_client.datacenters_servers_volumes_post(datacenter_id=datacenter, server_id=server_id,
                                                                  volume=volume)
        except Exception as e:
            module.fail_json(msg='failed to attach volume: %s' % to_native(e))


def get_module_arguments():
    arguments = {}

    for option_name, option in OPTIONS.items():
      arguments[option_name] = {
        'type': option['type'],
      }
      for key in ['choices', 'default', 'aliases', 'no_log', 'elements']:
        if option.get(key) is not None:
          arguments[option_name][key] = option.get(key)

      if option.get('env_fallback'):
        arguments[option_name]['fallback'] = (env_fallback, [option['env_fallback']])

      if len(option.get('required', [])) == len(STATES):
        arguments[option_name]['required'] = True

    return arguments


def get_sdk_config(module, sdk):
    username = module.params.get('username')
    password = module.params.get('password')
    token = module.params.get('token')
    api_url = module.params.get('api_url')

    if token is not None:
        # use the token instead of username & password
        conf = {
            'token': token
        }
    else:
        # use the username & password
        conf = {
            'username': username,
            'password': password,
        }

    if api_url is not None:
        conf['host'] = api_url
        conf['server_index'] = None

    return sdk.Configuration(**conf)


def check_required_arguments(module, state, object_name):
    # manually checking if token or username & password provided
    if (
        not module.params.get("token")
        and not (module.params.get("username") and module.params.get("password"))
    ):
        module.fail_json(
            msg='Token or username & password are required for {object_name} state {state}'.format(
                object_name=object_name,
                state=state,
            ),
        )

    for option_name, option in OPTIONS.items():
        if state in option.get('required', []) and not module.params.get(option_name):
            module.fail_json(
                msg='{option_name} parameter is required for {object_name} state {state}'.format(
                    option_name=option_name,
                    object_name=object_name,
                    state=state,
                ),
            )


def main():
    module = AnsibleModule(argument_spec=get_module_arguments(), supports_check_mode=True)

    if not HAS_SDK:
        module.fail_json(msg='ionoscloud is required for this module, run `pip install ionoscloud`')

    state = module.params.get('state')
    with ApiClient(get_sdk_config(module, ionoscloud)) as api_client:
        api_client.user_agent = USER_AGENT
        check_required_arguments(module, state, OBJECT_NAME)

        try:
            if state == 'absent':
                module.exit_json(**delete_volume(module, api_client))
            elif state == 'present':
                module.exit_json(**create_volume(module, api_client))
            elif state == 'update':
                module.exit_json(**update_volume(module, api_client))
        except Exception as e:
            module.fail_json(msg='failed to set {object_name} state {state}: {error}'.format(object_name=OBJECT_NAME, error=to_native(e), state=state))


if __name__ == '__main__':
    main()
