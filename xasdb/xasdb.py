#!/usr/bin/env python
"""
Principle Python interface to XAS Data Library
requires SQLAlchemy 0.6 or higher

Main Class:  XASDataLibrary

"""

import os
import sys
import time
import random
import json
import logging
import numpy as np
from datetime import datetime

from base64 import b64encode
try:
    from hashlib import pbkdf2_hmac
except ImportError:
    from .pbkdf2_local import pbkdf2_hmac

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import sessionmaker,  mapper, relationship, backref
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import  NoResultFound

from xdifile import XDIFile

PW_ALGORITHM = 'sha512'
PW_NROUNDS   = 120000

def isXASDataLibrary(dbname):
    """test if a file is a valid XAS Data Library file:
       must be a sqlite db file, with tables named
          'info', 'spectra', 'sample', 'element' and 'energy_units'
       the 'element' table must have more than 90 rows and the
       'info' table must have an entries named 'version' and 'create_date'
    """

    try:
        engine  = create_engine('sqlite:///%s' % dbname)
        metadata =  MetaData(engine)
        metadata.reflect()
    except:
        return False

    if ('info' in metadata.tables and
        'spectra' in metadata.tables and
        'sample' in metadata.tables and
        'element' in metadata.tables and
        'energy_units' in metadata.tables):

        elements = metadata.tables['element'].select().execute().fetchall()
        if len(elements) > 90:
            info = metadata.tables['info'].select().execute().fetchall()
            keys = [row.key for row in info]
            return ('version' in keys and 'create_date' in keys)
    return False

def json_encode(val):
    "simple wrapper around json.dumps"
    if val is None or isinstance(val, (str, unicode)):
        return val
    if isinstance(val, np.ndarray):
        val = val.flatten().tolist()
    return  json.dumps(val)

def valid_score(score, smin=0, smax=5):
    """ensure that the input score is an integr
    in the range [smin, smax]  (inclusive)"""
    return max(smin, min(smax, int(score)))

def unique_name(name, namelist, maxcount=100, msg='spectrum'):
    """
    find a name that is not in namelist by making
       name (1),  name (2), etc
    up to maxcount, at which point an exception is raised.
    """
    basename, count = name, 0
    while name in namelist:
        count += 1
        if count > maxcount:
            msg = "a %s named '%s' already exists"  % (msg, name)
            raise XASDBException(msg)
        name = "%s (%i)" % (basename, count)
    return name

def isotime2datetime(isotime):
    sdate, stime = isotime.replace('T', ' ').split(' ')
    syear, smon, sday = [int(x) for x in sdate.split('-')]
    sfrac = '0'
    if '.' in stime:
        stime, sfrac = stime.split('.')
    shour, smin, ssec  = [int(x) for x in stime.split(':')]
    susec = int(1e6*float('.%s' % sfrac))

    return datetime(syear, smon, sday, shour, smin, ssec, susec)

def fmttime(dtime=None):
    if dtime is None:
        dtime = datetime.now()
    return dtime.strftime('%Y-%m-%d %H:%M:%S')


def None_or_one(val, msg='Expected 1 or None result'):
    """expect result (as from query.all() to return
    either None or exactly one result"""
    if len(val) == 1:
        return val[0]
    elif len(val) == 0:
        return None
    else:
        raise XASDBException(msg)

def apply_orderby(q, tab, orderby=None):
    """apply an order_by to a query to sort results"""
    if orderby is not None:
        key = getattr(tab.c, orderby, None)
        if key is None:
            key = getattr(tab.c, "%s_id" % orderby, None)
        if key is not None:
            q = q.order_by(key)
    return q

def slow_string_compare(a, b):
    """
    does a slow-as-possible compare of 2 strings, a and b
    returns whether the two strings are equal
    this is meant to confuse and slow down attempts to guess / crack
    passwords that time how long a string comparison takes to fail.
    """
    isgood = 0
    if len(a) != len(b): isgood = 1
    time.sleep(3.e-5*(len(a)*(1+4*random.random())))
    for x, y in zip(a, b):
        isgood |= ord(x) ^ ord(y)
    return isgood == 0


class XASDBException(Exception):
    """XAS DB Access Exception: General Errors"""
    def __init__(self, msg):
        Exception.__init__(self)
        self.msg = msg
    def __str__(self):
        return self.msg


class _BaseTable(object):
    "generic class to encapsulate SQLAlchemy table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s' % getattr(self, 'name', 'UNNAMED')]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Info(_BaseTable):
    "general information table (versions, etc)"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s=%s' % (getattr(self, 'key', '?'),
                               getattr(self, 'value', '?'))]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Mode(_BaseTable):
    "collection mode table"
    pass

class Facility(_BaseTable):
    "facility table"
    pass

class Beamline(_BaseTable):
    "beamline table"
    pass

class EnergyUnits(_BaseTable):
    "Energy Units table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s' % getattr(self, 'units', '')]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Edge(_BaseTable):
    "edge table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s' % getattr(self, 'name', 'X')]
        # '%s' % getattr(self, 'level', '')]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Element(_BaseTable):
    "element table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%s' % getattr(self, 'symbol', 'NU'),
                  'Z=%i' % getattr(self, 'z', 0),
                  '%s' % getattr(self, 'name', 'UNNAMED'),
                  ]
        return "<%s(%s)>" % (name, ', '.join(fields))


class Ligand(_BaseTable):
    "ligand table"
    pass

class Crystal_Structure(_BaseTable):
     "crystal structure table"
     pass

class Citation(_BaseTable):
    "literature citation table"
    pass

class Person(_BaseTable):
    "person table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = [getattr(self, 'name', ''),
                  getattr(self, 'email', 'NO EMAIL')]
        return "<%s(%s)>" % (name, ', '.join(fields))

class Spectrum_Ligand(_BaseTable):
    "spectrum ligand"
    ligand, spectrum = None, None

class Spectrum_Rating(_BaseTable):
    "spectra rating"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%i' % (int(getattr(self, 'score', 0)))]
        if getattr(self, 'spectra', None) is not None:
            fields.append('Spectrum %i' % getattr(self, 'spectra', 0))

        return "<%s(%s)>" % (name, ', '.join(fields))


class Suite_Rating(_BaseTable):
    "suite rating table"
    def __repr__(self):
        name = self.__class__.__name__
        fields = ['%i' % (int(getattr(self, 'score', 0)))]
        if getattr(self, 'suite', None) is not None:
            fields.append('Suite %i' % getattr(self, 'suite', 0))

        return "<%s(%s)>" % (name, ', '.join(fields))

class Suite(_BaseTable):
    "suite table"
    pass

class Sample(_BaseTable):
    "sample table"
    pass

class Spectrum(_BaseTable):
    "spectra table"
    pass

class Spectrum_Mode(_BaseTable):
    "spectra table"
    pass


class XASDataLibrary(object):
    """full interface to XAS Spectral Library"""
    def __init__(self, dbname=None, server= 'sqlite', user='',
                 password='',  host='', port=5432, logfile=None):
        self.engine = None
        self.session = None
        self.metadata = None
        self.logfile = logfile
        if dbname is not None:
            self.connect(dbname, server=server, user=user,
                         password=password, port=port, host=host)

    def connect(self, dbname, server='sqlite', user='',
                password='', port=5432, host=''):
        "connect to an existing database"

        self.dbname = dbname
        if server.startswith('sqlit'):
            self.engine = create_engine('sqlite:///%s' % self.dbname)
        else:
            conn_str= 'postgresql://%s:%s@%s:%i/%s'
            self.engine = create_engine(conn_str % (user, password, host,
                                                    port, dbname))

        self.metadata =  MetaData(self.engine)
        try:
            self.metadata.reflect()
        except:
            raise XASDBException('%s is not a valid database' % dbname)

        tables = self.tables = self.metadata.tables
        self.session = sessionmaker(bind=self.engine)()
        self.query   = self.session.query


        mapper(Info,             tables['info'])
        mapper(Sample,           tables['sample'])
        mapper(Spectrum_Rating,  tables['spectrum_rating'])
        mapper(Spectrum_Ligand,  tables['spectrum_ligand'])
        mapper(Spectrum_Mode,    tables['spectrum_mode'])
        mapper(Suite_Rating,     tables['suite_rating'])
        mapper(EnergyUnits,      tables['energy_units'])
        mapper(Spectrum,         tables['spectrum'])

        relate = relationship

        mapper(Mode, tables['mode'],
               properties={'spectrum': relate(Spectrum, backref='mode',
                                        secondary=tables['spectrum_mode'])})

        mapper(Edge, tables['edge'],
               properties={'spectrum': relate(Spectrum, backref='edge')})

        mapper(Element, tables['element'],
               properties={'spectrum': relate(Spectrum, backref='element')})

        mapper(Beamline, tables['beamline'],
               properties={'spectrum': relate(Spectrum, backref='beamline')})

        mapper(Citation, tables['citation'],
               properties={'spectrum': relate(Spectrum, backref='citation')})

        mapper(Ligand,   tables['ligand'],
               properties={'spectrum': relate(Spectrum, backref='ligand',
                                              secondary=tables['spectrum_ligand'])})

        mapper(Crystal_Structure,   tables['crystal_structure'],
               properties={'samples': relate(Sample, backref='structure')})

        mapper(Facility, tables['facility'],
               properties={'beamlines': relate(Beamline, backref='facility')})

        mapper(Person,   tables['person'],
               properties={'suites': relate(Suite, backref='person'),
                           'samples': relate(Sample, backref='person'),
                           'spectrum': relate(Spectrum, backref='person')})

        mapper(Suite,   tables['suite'],
        properties={'spectrum': relate(Spectrum, backref='suite',
                                        secondary=tables['spectrum_suite'])})

        self.update_mod_time =  None

        if self.logfile is None and server.startswith('sqlit'):
            lfile = self.dbname
            if lfile.endswith('.xdl'):
                lfile = self.logfile[:-4]
            self.logfile = "%s.log" % lfile
            logging.basicConfig()
            logger = logging.getLogger('sqlalchemy.engine')
            logger.addHandler(logging.FileHandler(self.logfile))


    def close(self):
        "close session"
        self.session.commit()
        self.session.flush()
        self.session.close()

    def set_info(self, key, value):
        """set key / value in the info table"""
        table = self.tables['info']
        vals  = self.query(table).filter(Info.key==key).all()
        if len(vals) < 1:
            # none found -- insert
            table.insert().execute(key=key, value=value)
        else:
            table.update(whereclause="key='%s'" % key).execute(value=value)

    def set_mod_time(self):
        """set modify_date in info table"""
        if self.update_mod_time is None:
            self.update_mod_time = self.tables['info'].update(
                whereclause="key='modify_date'")
        self.update_mod_time.execute(value=fmttime())

    def addrow(self, tablename, **kws):
        """add generic row"""
        table = self.tables[tablename]
        table.insert().execute(**kws)
        self.set_mod_time()
        self.session.commit()

    def filtered_query(self, tablename, **kws):
        """
        return query of table with any equality filter on columns

        examples:

        >>> db.filtered_query('element', z=30)
        >>> db.filtered_query('spectrum', person_id=3)

        will return all rows from table

        """
        table = self.tables[tablename]
        query = self.query(table)

        for key, val in kws.items():
            if key in table.c and val is not None:
                query = query.filter(getattr(table.c, key)==val)
        return query.all()

    def get_facility(self, just_one=False, **kws):
        """return facility or list of facilities"""

        out = self.filtered_query('facility', **kws)
        if len(out) > 1:
            return out

        return None_or_one(out)

    def get_element(self, val):
        """return element z, name, symbol from one of z, name, symbol"""
        key = 'symbol'
        if isinstance(val, int):
            key = 'z'
        elif len(val) > 2:
            key = 'name'
        args = {}
        args[key] = val
        return None_or_one(self.filtered_query('element', **args))

    def get_elements(self):
        """return list of elements z, name, symbol"""
        return self.filtered_query('element')

    def get_edge(self, val, key='name'):
        """return edge by name  or id"""
        if isinstance(val, int):
            key = 'id'
        kws = {key: val}
        return None_or_one(self.filtered_query('edge', **kws))

    def get_edges(self):
        """return list of edges"""
        return self.filtered_query('edge')

    def add_energy_units(self, units, notes=None, **kws):
        """add Energy Units: units required
        notes  optional
        returns EnergyUnits instance"""
        self.addrow('energy_units', units=units, notes=notes, **kws)

    def get_sample(self, sid):
        """return sample by id"""
        return None_or_one(self.filtered_query('sample', id=sid))

    def add_mode(self, name, notes='', **kws):
        """add collection mode: name required
        returns Mode instance"""
        return self.addrow('mode', name=name, notes=notes, **kws)

    def add_crystal_structure(self, name, notes='',
                               format=None, data=None, **kws):
         """add data format: name required
         returns Format instance"""
         kws['notes'] = notes
         kws['format'] = format
         kws['data'] = data
         return self.addrow(Crystal_Structure, ('name',), (name,), **kws)

    def add_edge(self, name, level):
        """add edge: name and level required
        returns Edge instance"""
        return self.addrow('edge', name=name, level=level)

    def add_facility(self, name, notes='', **kws):
        """add facilty by name, return Facility instance"""
        return self.addrow('facility', name=name, notes=notes, **kws)

    def add_beamline(self, name, facility_id=None,
                     xray_source=None,  notes='', **kws):
        """add beamline by name, with facility:
               facility= Facility instance or id
               returns Beamline instance"""
        return self.addrow('beamline', name=name, xray_source=xray_source,
                            notes=notes, facility_id=facility_id, **kws)

    def add_citation(self, name, **kws):
        """add literature citation: name required
        returns Citation instance"""
        return self.addrow('citation', name=name, **kws)

    def add_info(self, key, value):
        """add Info key value pair -- returns Info instance"""
        return self.addrow('info', key=key, value=value)

    def add_ligand(self, name, **kws):
        """add ligand: name required
        returns Ligand instance"""
        return self.addrow('ligand', name=name, **kws)

    def add_person(self, name, email,
                   affiliation='', password=None, con='false', **kws):
        """add person: arguments are
        name, email with affiliation and password optional
        returns Person instance"""
        person = self.addrow('person', email=email, name=name,
                             affiliation=affiliation,
                             confirmed=con, **kws)

        if password is not None:
            self.set_person_password(email, password)

    def get_person(self, val, key='email'):
        """get person by email"""
        if isinstance(val, int):
            key = 'id'
        kws = {key: val}

        return None_or_one(self.filtered_query('person', **kws),
                           "expected 1 or None person")

    def get_persons(self, **kws):
        """return list of people"""
        return self.filtered_query('person')

    def set_person_password(self, email, password):
        """ set secure password for person"""
        salt   = b64encode(os.urandom(24))
        result = b64encode(pbkdf2_hmac(PW_ALGORITHM, password, salt, PW_NROUNDS))
        hash   = '%s$%i$%s$%s' % (PW_ALGORITHM, PW_NROUNDS, salt, result)

        table = self.tables['person']
        table.update(whereclause="email='%s'" % email).execute(password=hash)

    def test_person_password(self, email, password):
        """test password for person, returns True if valid"""

        table = self.tables['person']
        row  = table.select(table.c.email==email).execute().fetchone()
        try:
            algo, niter, salt, hash = row.password.split('$')
            niter = int(niter)
        except:
            return False
        test_pw = b64encode(pbkdf2_hmac(algo, password, salt, niter))
        return slow_string_compare(hash, test_pw)

    def test_person_confirmed(self, email):
        """test if account for a person is confirmed"""

        table = self.tables['person']
        row  = table.select(table.c.email==email).execute().fetchone()
        return row.confirmed.lower() == 'true'

    def person_unconfirm(self, email):
        """ sets a person to 'unconfirmed' status, pending confirmation,
        returns hash, which must be used to confirm person"""
        hash = b64encode(os.urandom(24)).replace('/', '_')
        table = self.tables['person']
        table.update(whereclause="email='%s'" % email).execute(confirmed=hash)
        return hash

    def person_test_confirmhash(self, email, hash):
        """test if a person's confirmation hash is correct"""
        tab = self.tables['person']
        row = tab.select(tab.c.email==email).execute().fetchone()
        return slow_string_compare(hash, row.confirmed)

    def person_confirm(self, email, hash):
        """try to confirm a person,
        test the supplied hash for confirmation,
        setting 'confirmed' to 'true' if correct.
        """
        tab = self.tables['person']
        row = tab.select(tab.c.email==email).execute().fetchone()
        is_confirmed = False
        if hash == row.confirmed:
            tab.update(whereclause="email='%s'" % email).execute(confirmed='true')
            is_confirmed = True
        return is_confirmed

    def add_sample(self, name, person_id, notes='', **kws):
        """add sample: name required
        returns Sample instance"""

        kws['name'] = name
        kws['person_id'] = person_id
        kws['notes'] = notes
        #if crystal_structure is not None:
        #    kws['crystal_structure_id'] = crystal_structure
        tab = self.tables['sample']
        tab.insert().execute(**kws)

    def add_suite(self, name, notes='', person_id=None, **kws):
        """add suite: name required
        returns Suite instance"""
        return self.addrow('suite', name=name, notes=notes,
                            person_id=person_id, **kws)

    def del_suite(self, suite_id):
        table = self.tables['suite']
        table.delete().where(table.c.id==suite_id).execute()
        table = self.tables['spectrum_suite']
        table.delete().where(table.c.suite_id==suite_id).execute()
        table = self.tables['suite_rating']
        table.delete().where(table.c.id==suite_id).execute()
        self.set_mod_time()
        self.session.commit()

    def remove_spectrum_from_suite(self, suite_id, spectrum_id):
        tab = self.tables['spectrum_suite']
        rows = tab.select().where(tab.c.suite_id==suite_id
                                  ).where(tab.c.spectrum_id==spectrum_id
                                          ).execute().fetchall()
        for row in rows:
            tab.delete().where(tab.c.id==row.id).execute()
        self.set_mod_time()
        self.session.commit()

    def del_spectrum(self, sid):
        table = self.tables['spectrum']
        table.delete().where(table.c.id==sid).execute()
        table = self.tables['spectrum_suite']
        table.delete().where(table.c.spectrum_id==sid).execute()
        table = self.tables['spectrum_rating']
        table.delete().where(table.c.id==sid).execute()

        self.set_mod_time()
        self.session.commit()

    def set_suite_rating(self, person_id, suite_id, score, comments=None):
        """add a score to a suite:"""
        kws = {'score': valid_score(score),
               'person_id': person_id, 'suite_id': suite_id,
               'datetime': datetime.now(), 'comments': ''}
        if comments is not None:
            kws['comments'] = comments

        tab = self.tables['suite_rating']
        rowid = None
        for row in tab.select(tab.c.suite_id==suite_id).execute().fetchall():
            if row.person_id == person_id:
                rowid = row.id

        if rowid is None:
            tab.insert().execute(**kws)
        else:
            tab.update(whereclause="id='%i'" % rowid).execute(**kws)
        self.session.commit()

        sum = 0
        rows = tab.select(tab.c.suite_id==suite_id).execute().fetchall()
        for row in rows:
            sum += 1.0*row.score

        rating = 'No ratings'
        if len(rows) > 0:
            rating = '%.1f (%i ratings)' % (sum/len(rows), len(rows))

        stab = self.tables['suite']
        stab.update(whereclause="id='%i'" % suite_id).execute(rating_summary=rating)


    def set_spectrum_rating(self, person_id, spectrum_id, score, comments=None):
        """add a score to a spectrum: person_id, spectrum_id, score, comment
        score is an integer value 0 to 5"""
        kws = {'score': valid_score(score),
               'person_id': person_id, 'spectrum_id': spectrum_id,
               'datetime': datetime.now(), 'comments': ''}
        if comments is not None:
            kws['comments'] = comments


        tab = self.tables['spectrum_rating']
        rowid = None
        for row in tab.select(tab.c.spectrum_id==spectrum_id).execute().fetchall():
            if row.person_id == person_id:
                rowid = row.id

        if rowid is None:
            tab.insert().execute(**kws)
        else:
            tab.update(whereclause="id='%i'" % rowid).execute(**kws)

        self.session.commit()

        sum = 0
        rows = tab.select(tab.c.spectrum_id==spectrum_id).execute().fetchall()
        for row in rows:
            sum += 1.0*row.score

        rating = 'No ratings'
        if len(rows) > 0:
            rating = '%.1f (%i ratings)' % (sum/len(rows), len(rows))

        stab = self.tables['spectrum']
        stab.update(whereclause="id='%i'" % spectrum_id).execute(rating_summary=rating)



    def update(self, tablename, where, use_id=True, **kws):
        """update a row (by id) in a table (by name) using keyword args
        db.update('spectrum', 5, **kws)

        """
        table = self.tables[tablename]
        if use_id:
            where ="id='%i'" % where
        table.update(whereclause=where).execute(**kws)
        self.set_mod_time()
        self.session.commit()

    def add_spectrum(self, name, notes='', d_spacing=-1, energy_notes='',
                     i0_notes='', itrans_notes='', ifluor_notes='',
                     irefer_notes='', submission_date=None,
                     collection_date=None, temperature='', energy=None,
                     i0=None, itrans=None, ifluor=None, irefer=None,
                     energy_stderr=None, i0_stderr=None,
                     itrans_stderr=None, ifluor_stderr=None,
                     irefer_stderr=None, energy_units=None, person=None,
                     edge=None, element=None, sample=None, beamline=None,
                     data_format=None, citation=None, reference_used=0,
                     reference_mode=None, reference_sample=None, **kws):

        """add spectrum: name required
        returns Spectrum instance"""

        stab = self.tables['spectrum']
        spectrum_names = [s.name for s in stab.select().execute()]

        if name in spectrum_names:
            raise XASDBException("A spectrum named '%s' already exists" % name)

        dlocal = locals()
        # simple values

        for attr in ('notes', 'energy_notes', 'i0_notes', 'itrans_notes',
                     'ifluor_notes', 'irefer_notes', 'temperature',
                     'd_spacing', 'reference_used'):
            kws[attr] = dlocal.get(attr, '')

        # arrays
        for attr in ('energy', 'i0', 'itrans', 'ifluor', 'irefer',
                     'energy_stderr', 'i0_stderr', 'itrans_stderr',
                     'ifluor_stderr', 'irefer_stderr'):
            val = ''
            if dlocal[attr] is not None:
                val = json_encode(dlocal.get(attr, ''))
            kws[attr] = val

        # dates
        if submission_date is None:
            submission_date = datetime.now()
        for attr, val in (('submission_date', submission_date),
                          ('collection_date', collection_date)):
            if isinstance(val, (str, unicode)):
                try:
                    val = isotime2datetime(val)
                except ValueError:
                    val = None
            if val is None:
                val = datetime(1,1,1)
            kws[attr] = val

        # foreign keys, pointers to other tables
        kws['beamline_id'] = beamline
        kws['person_id'] = person
        kws['edge_id'] = self.get_edge(edge).id
        kws['element_z'] = self.get_element(element).z
        kws['energy_units_id'] = self.filtered_query('energy_units', name=energy_units)[0].id

        kws['sample_id'] = sample
        kws['citation_id'] = citation
        kws['reference_id'] = reference_sample
        kws['reference_mode_id'] = reference_mode

        self.addrow('spectrum', name=name, **kws)
        table = self.tables['spectrum']
        return self.query(table).filter(table.c.name == name).one()


    def get_beamlines(self, facility=None, orderby='id'):
        """get all beamlines for a facility
        Parameters
        --------
        facility  id, name, or Facility instance for facility

        Returns
        -------
        list of matching beamlines

        """
        tab = self.tables['beamline']
        fac_id = None
        if isinstance(facility, Facility):
            fac_id = facility.id
        elif isinstance(facility, int):
            fac_id = facility
        elif isinstance(facility, basestring):
            ftab = self.tables['facility']
            row  = ftab.select(ftab.c.name==facility).execute().fetchone()
            fac_id = row.id

        if fac_id is not None:
            query = tab.select(tab.c.facility_id==fac_id)
        else:
            query = tab.select()

        query = apply_orderby(query, tab, orderby)
        return query.execute().fetchall()


    def get_suite_ratings(self, spectrum):
        "get all ratings for a suite"
        raise NotImplementedError

    def get_spectrum_ratings(self, spectrum):
        "get all ratings for a spectrum"
        raise NotImplementedError

    def set_spectrum_mode(self, spectrum_id, mode_id):
        """set a mode for a spectrum"""
        self.addrow('spectrum_mode',
                     spectrum_id=spectrum_id, mode_id=mode_id)

    def get_spectrum_mode(self,id):
        """get mode for a spectrum"""
        tab = self.tables['spectrum_mode']
        return tab.select().where(tab.c.spectrum_id == id).execute().fetchall()

    def get_spectrum(self, id):
        """ get spectrum by id"""
        tab = self.tables['spectrum']
        return tab.select().where(tab.c.id == id).execute().fetchone()

    def get_spectra(self, edge=None, element=None, beamline=None,
                    person=None, mode=None, sample=None, facility=None,
                    suite=None, citation=None, ligand=None, orderby='id'):
        """get all spectra matching some set of criteria

        Parameters
        ----------
        edge       by Name
        element    by Z, Symbol, or Name
        person     by email
        beamline   by name
        facility
        mode
        sample
        citation
        ligand
        suite
        """
        edge_id, element_z, person_id, beamline_id = None, None, None, None

        tab = self.tables['spectrum']
        query = tab.select()

        # edge
        if isinstance(edge, Edge):
            edge_id = edge.id
        elif edge is not None:
            edge_id = self.get_edge(edge).id
        if edge_id is not None:
            query = query.where(tab.c.edge_id==edge_id)

        # element
        if isinstance(element, Element):
            element_z = element.z
        elif element is not None:
            element_z = self.get_element(element).z
        if element_z is not None:
            query = query.where(tab.c.element_z==element_z)

        # beamline
        if isinstance(beamline, Beamline):
            beamline_id = beamline.id
        elif beamline is not None:
            beamline_id = self.get_beamline(name=beamline).id
        if beamline_id is not None:
            query = query.where(tab.c.beamline_id==beamline_id)

        # person
        if isinstance(person, Person):
            person_id = person.id
        elif person is not None:
            person_id = self.get_person(person).id
        if person_id is not None:
            query = query.where(tab.c.person_id==person_id)

        query = apply_orderby(query, tab, orderby)
        return query.execute().fetchall()

    def add_xdifile(self, fname, person=None, create_sample=True, **kws):

        try:
            fh  = open(fname, 'r')
            filetext  = fh.read()
        except:
            filetext = ''
        finally:
            fh.close()

        xfile = XDIFile(fname)
        path, fname = os.path.split(fname)

        now = fmttime()

        spectrum_name = fname
        if spectrum_name.endswith('.xdi'):
            spectrum_name = spectrum_name[:-4]


        stab = self.tables['spectrum']

        _s_names = [s.name for s in stab.select().execute()]
        spectrum_name = unique_name(spectrum_name, _s_names)

        try:
            c_date = xfile.attrs['scan']['start_time']
        except:
            c_date = 'collection date unknown'
        d_spacing = xfile.dspacing
        edge      = xfile.edge
        element   = xfile.element
        energy    = xfile.energy
        comments  = ''
        if hasattr(xfile, 'comments'):
            comments = xfile.comments

        if hasattr(xfile, 'i0'):
            i0 = xfile.i0

        #
        modes = []
        ifluor = itrans = irefer = None
        if hasattr(xfile, 'itrans'):
            itrans = xfile.itrans
            modes.append('transmission')
        elif hasattr(xfile, 'i1'):
            itrans = xfile.i1
            modes.append('transmission')

        if hasattr(xfile, 'ifluor'):
            ifluor= xfile.ifluor
            modes.append('fluorescence')

        elif hasattr(xfile, 'ifl'):
            ifluor= xfile.ifl
            modes.append('fluorescence')

        # special case: mutrans given,
        # itrans not available,
        # and maybe i0 not available
        if (hasattr(xfile, 'mutrans') and
            not hasattr(xfile, 'itrans')):
            if not hasattr(xfile, 'i0'):
                i0 = np.ones(len(xfile.mutrans))*1.0
                itrans = np.exp(-xfile.mutrans)
            modes.append('transmission')

        if (hasattr(xfile, 'mufluor') and
            not hasattr(xfile, 'ifluor')):
            if not hasattr(xfile, 'i0'):
                i0 = np.ones(len(xfile.mufluor))*1.0
                ifluor = xfile.mufluor
            modes.append('fluorescence')


        if (hasattr(xfile, 'munorm')):
            i0 = np.ones(len(xfile.munorm))*1.0
            ifluor = xfile.munorm
            modes.append('fluorescence, unitstep')

        refer_used = 0
        if hasattr(xfile, 'irefer'):
            refer_used = 1
            irefer= xfile.irefer
        elif hasattr(xfile, 'i2'):
            refer_used = 1
            irefer= xfile.i2

        en_units = 'eV'
        for index, value in xfile.attrs['column'].items():
            words = value.split()
            if len(words) > 1:
                if (value.lower().startswith('energy') or
                    value.lower().startswith('angle') ):
                    en_units = words[1]

        if isinstance(person, Person):
            person_id = person.id
        else:
            person_id = self.get_person(person).id

        sample_id = None
        if create_sample:
            try:
                sattrs  = xfile.attrs['sample']
            except:
                sattrs = {'name': 'unknown',
                          'prep': 'unknown'}

            formula, prep, notes = '', '', ''
            notes = "sample for '%s', uploaded %s" % (fname, now)
            if 'name' in sattrs:
                sname = sattrs.pop('name')
            if 'prep' in sattrs:
                prep = sattrs.pop('prep')
            if 'formula' in sattrs:
                formula = sattrs.pop('formula')
            if len(sattrs) > 0:
                notes  = '%s\n%s' % (notes, json_encode(sattrs))
            self.add_sample(sname, person_id, formula=formula,
                            preparation=prep, notes=notes)

            stab = self.tables['sample']
            sample = self.query(stab).filter(stab.c.name==sname).all()
            # if len(sample) > 1:
                # print( 'Warning: multiple (%i) samples name %s' % (len(sample), sname))
            sample = sample[0]

            sample_id = sample.id
            sample_ref_id = None
            if 'reference' in sattrs:
                rname = sattrs['reference']
                note = "reference for '%s', uploaded %s" % (fname, now)
                try:
                    rsample = self.query(stab).filter(stab.c.name==rname).one()
                except:
                    self.add_sample(rname, person_id, formula='',
                                    preparation='', notes=notes)
                    rsample = self.query(stab).filter(stab.c.name==rname).one()
                sample_ref_id = rsample.id


        beamline = None
        beamline_name  = xfile.attrs['beamline']['name']
        notes = json_encode(xfile.attrs)
        spectrum_name = "%s (%s)" % (sname, spectrum_name)
        
        print spectrum_name,modes    
        
        spec  = self.add_spectrum(spectrum_name, d_spacing=d_spacing,
                                  collection_date=c_date, person=person_id,
                                  beamline=beamline, edge=edge, element=element,
                                  energy=energy, energy_units=en_units,
                                  i0=i0,itrans=itrans, ifluor=ifluor,
                                  irefer=irefer,
                                  sample=sample_id,
                                  comments=comments,
                                  notes=notes,
                                  filetext=filetext,
                                  reference_sample=sample_ref_id)


        modes_map = {}
        for row in self.tables['mode'].select().execute().fetchall():
            modes_map[row.name] = row.id
        for mode in modes:
            mode_id = modes_map.get(mode, None)
            if mode_id is not None:
                self.set_spectrum_mode(spec.id, mode_id)
