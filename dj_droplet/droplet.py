import sys
import time
from PyInquirer import prompt, Separator
from examples import custom_style_1, custom_style_2, custom_style_3
from prompt_toolkit.validation import ValidationError, Validator
import py_doctl as doctl
from py_doctl import DOCtlError
import socket


class MultipleItemException(Exception):
    pass


class DropletExistException(Exception):
    pass


class DoCtlManager:

    def __init__(self, doctl, klass) -> None:
        self.doctl = doctl
        self.klass = klass

    def _get_list(self):
        return self.doctl.list()

    def list(self):
        return [self.klass(item) for item in self._get_list()]

    def get(self, id):
        obj = self.doctl.get(str(id))
        if len(obj) > 1:
            raise MultipleItemException(
                f'Got two or more items of class {self.klass} for ID: {id}'
            )
        elif len(obj) < 1:
            return None
        return self.klass(obj[0])


class DoCtlManagerList(DoCtlManager):

    def _get_list(self):
        return self.doctl()

    def get(self, slug):
        if not slug:
            return None
        for item in self.list():
            if item.slug == slug:
                return item


class DoCtl(dict):

    _manager = DoCtlManager
    _doctl = doctl

    @classmethod
    def objects(cls):
        return cls._manager(cls._doctl, cls)

    @property
    def name(self):
        return self.get('name', None)

    @property
    def slug(self):
        return self.get('slug', None)

    def __str__(self) -> str:
        if self.slug:
            return self.slug
        return super().__str__()

    @property
    def display_name(self):
        val = ""
        if self.name:
            val += f'{self.name} | '
        if self.slug:
            val += f'{self.slug} | '
        if val:
            return val
        return self.__str__()


class DropletManager(DoCtlManager):
    def create(self, name, image, region, size, **kwargs):
        if droplet_exists(name):
            raise DropletExistException(
                f'Droplet with name {name} already exists')
        res = self.doctl.create(name, image, region, size, **kwargs)
        return self.klass(res[0])


class Droplet(DoCtl):
    _doctl = doctl.compute.droplet
    _manager = DropletManager

    @property
    def image(self):
        image_dict = self.get('image')
        if image_dict:
            return image_dict.get('slug', None)

    @property
    def size(self):
        return self.get('size_slug', None)

    @property
    def region(self):
        return self.get('region', {}).get('slug', None)

    @property
    def publicIp4(self):
        reg = self.get('networks', {}).get('v4', [])
        for item in reg:
            if item.get('type', None) == 'public':
                return item.get('ip_address', None)

    @property
    def display_name(self):
        return (
            f"{self.name: ^20} | "
            f"{self.publicIp4: ^20} | "
            f"{self.image: ^10} | "
            f"{self.size: ^10} | "
            f"{self.region: ^10}"
        )


class Region(DoCtl):
    _doctl = doctl.compute.region_list
    _manager = DoCtlManagerList

    @property
    def sizes(self):
        return self.get('sizes', None)


class Image(DoCtl):
    _doctl = doctl.compute.image.list_distribution
    _manager = DoCtlManagerList

    @property
    def name(self):
        return f"{self.get('distribution')}  {self.get('name')}"


class Size(DoCtl):
    _doctl = doctl.compute.size_list
    _manager = DoCtlManagerList

    @property
    def display_name(self):
        return (
            f"{self.get('slug') : ^20} | "
            f"{self.get('vcpus') : ^10} core | "
            f"{self.get('memory') : ^10} | "
            f"{self.get('disk') : ^10} | "
            f"{self.get('description') : ^20} | "
            f"{self.get('price_monthly') : ^10}"
        )

    @classmethod
    def display_header(cls):
        return (
            f"{'slug' : ^20} | "
            f"{'vcpus' : ^10} core | "
            f"{'memory MB' : ^10} | "
            f"{'disk GB' : ^10} | "
            f"{'description' : ^20} | "
            f"{'$/month' : ^10}"
        )


def image_choices(ans):
    return [
        {'name': item.display_name,
         'value': item}
        for item in Image.objects().list()
        if item.get('distribution').lower() == 'ubuntu'
    ]


def region_choices(ans):
    region_slugs = ans['image']['regions']
    regions = []
    for region in Region.objects().list():
        if region.slug in region_slugs:
            regions.append({'name': region.display_name, 'value': region})
    return regions


def size_choices(ans):
    size_slugs = ans['region']['sizes']
    sizes = [Separator(), Separator(Size.display_header()), ]
    for size in Size.objects().list():
        if size.slug in size_slugs:
            sizes.append({'name': size.display_name, 'value': size})
    sizes += [Separator(Size.display_header()), ]
    return sizes


def droplet_choices(ans):
    choices = [Separator()]
    for item in Droplet.objects().list():
        choices.append({'name': item.display_name, 'value': item})
    return choices


def droplet_name_validate(name):
    if not name:
        return "Enter a valid name"
    if droplet_exists(name):
        return f'A droplet with name {name} already exist, choose a different name'
    return True


def droplet_exists(name):
    try:
        doctl.compute.droplet.get(name)
    except DOCtlError as e:
        if 'could not be found' in e.output:
            return False
        raise e
    return True


def choose_droplet():
    """
    Returns:
        (Droplet: droplet, Bool: created)
    """
    def choices(ans):
        return [
            Separator(),
            {'name': 'Create a new droplet', 'value': {'create': True}},
        ] + droplet_choices(ans)
    ques = [
        {
            'type': 'list',
            'name': 'droplet',
            'message': 'Choose a droplet or create a new one.',
            'choices': choices,
        }
    ]

    answers = prompt(ques, style=custom_style_1)
    droplet = answers.get('droplet')
    if droplet.get('create', False):
        return (create_droplet(), True)
    return (droplet, False)


# TODO: delete_droplet list_droplet show_droplet_details
def delete_droplet():
    pass


def list_droplets():
    pass


def show_droplet_details():
    pass


def create_droplet():
    ques = [
        {
            'type': 'list',
            'name': 'image',
            'message': 'Choose a distribution image for your droplet:',
            'choices': image_choices,
        },
        {
            'type': 'list',
            'name': 'region',
            'message': 'Choose a region for your droplet:',
            'choices': region_choices,
        },
        {
            'type': 'list',
            'name': 'size',
            'message': 'Choose a size for your droplet:',
            'choices': size_choices,
        },
        {
            'type': 'input',
            'name': 'name',
            'message': 'Enter a name for your droplet:',
            'validate': droplet_name_validate,
        }
    ]

    ssh_keys = [item['id'] for item in get_ssh_keys()]
    answers = prompt(ques, style=custom_style_1)
    kwargs = {key: str(value) for key, value in answers.items()}
    droplet = Droplet.objects().create(**kwargs, ssh_keys=ssh_keys)
    print("Droplet created...\n")
    print('Waiting to get IPPADDR of the droplet... ')
    i = 0
    while not droplet.publicIp4:
        time.sleep(5)
        i += 1
        print(f'{i}')
        droplet = Droplet.objects().get(droplet['id'])
    return droplet


def import_ssh_key():
    ques = [
        {
            'type': 'input',
            'message': 'Enter the path of ssh public key file',
            'name': 'keyfile',
            'validate': lambda x: len(x) > 0,
            'default': '~/.ssh/id_rsa.pub',
        },
        {
            'type': 'input',
            'message': 'Enter a name for your ssh key',
            'name': 'name',
            'validate': lambda x: len(x) > 0,
            'default': socket.gethostname(),
        }
    ]
    ans = prompt(ques)
    return doctl.compute.ssh_key._import(ans['name'], ans['keyfile'])


def select_ssh_keys(sshkeys, selectedKeys=[]):
    choices = [{'name': item['name'], 'value':item}
               for item in sshkeys if item not in selectedKeys]
    choices += [Separator()]
    choices += [{'name': 'Import a new ssh key to you DO account',
                 'value': 'import'}, ]
    message1 = ''
    if len(selectedKeys) > 0:
        choices += [Separator()]
        choices += [{'name': 'Continue...',
                     'value': 'continue'}, ]
        choices += [{'name': 'Reset Selections',
                     'value': 'reset'}, ]
        message1 = f'Selected keys: {", ".join([item["name"] for item in selectedKeys])}'
    ques = [
        {
            'type': 'list',
            'message': 'Select the SSH keys to be added to your droplet. ' + message1,
            'name': 'keys',
            'choices': choices,
        }
    ]
    ans = prompt(ques)
    return ans['keys']


def get_ssh_keys():
    sshkeyselected = []

    while True:
        sshkeysall = doctl.compute.ssh_key.list()
        ans = select_ssh_keys(sshkeysall, sshkeyselected)
        if ans == 'import':
            sshkeyselected += [import_ssh_key()]
        elif ans == 'reset':
            sshkeyselected = []
        elif ans == 'continue':
            return sshkeyselected
        else:
            sshkeyselected += [ans]


if __name__ == "__main__":
    print(get_ssh_keys())
