# -*- coding: utf-8 -*-

"""
IDL Ref:
    https://thrift.apache.org/docs/idl
"""

from __future__ import absolute_import

import os
import types
from ply import lex, yacc
from .lexer import *  # noqa
from .exc import ThriftParserError, ThriftGrammerError
from ..thrift import gen_init, TType, TPayload, TException


def p_error(p):
    raise ThriftGrammerError('Grammer error %r at line %d' %
                             (p.value, p.lineno))


def p_start(p):
    '''start : header definition'''


def p_header(p):
    '''header : header_unit_ header
              |'''


def p_header_unit_(p):
    '''header_unit_ : header_unit ';'
                    | header_unit'''


def p_header_unit(p):
    '''header_unit : include
                   | namespace'''


def p_include(p):
    '''include : INCLUDE LITERAL'''
    thrift = thrift_stack[-1]
    path = os.path.join(include_dir_, p[2])
    child = parse(path)
    setattr(thrift, child.__name__, child)


def p_namespace(p):
    '''namespace : NAMESPACE namespace_scope IDENTIFIER'''
    # namespace is useless in thriftpy
    # if p[2] == 'py' or p[2] == '*':
    #     setattr(thrift_stack[-1], '__name__', p[3])


def p_namespace_scope(p):
    '''namespace_scope : '*'
                       | IDENTIFIER'''
    p[0] = p[1]


def p_sep(p):
    '''sep : ','
           | ';'
    '''


def p_definition(p):
    '''definition : definition definition_unit_
                  |'''


def p_definition_unit_(p):
    '''definition_unit_ : definition_unit ';'
                        | definition_unit'''


def p_definition_unit(p):
    '''definition_unit : const
                       | ttype
    '''


def p_const(p):
    '''const : CONST field_type IDENTIFIER '=' const_value'''

    try:
        val = _cast(p[2])(p[5])
    except AssertionError:
        raise ThriftParserError('Type error for constant %s at line %d' %
                                (p[3], p.lineno(3)))
    setattr(thrift_stack[-1], p[3], val)


def p_const_value(p):
    '''const_value : INTCONSTANT
                   | DUBCONSTANT
                   | LITERAL
                   | BOOLCONSTANT
                   | const_list
                   | const_map
                   | const_ref'''
    p[0] = p[1]


def p_const_list(p):
    '''const_list : '[' const_list_seq ']' '''
    p[0] = p[2]


def p_const_list_seq(p):
    '''const_list_seq : const_value sep const_list_seq
                      | const_value const_list_seq
                      |'''
    _parse_seq(p)


def p_const_map(p):
    '''const_map : '{' const_map_seq '}' '''
    p[0] = dict(p[2])


def p_const_map_seq(p):
    '''const_map_seq : const_map_item sep const_map_seq
                     | const_map_item const_map_seq
                     |'''
    _parse_seq(p)


def p_const_map_item(p):
    '''const_map_item : const_value ':' const_value '''
    p[0] = [p[1], p[3]]


def p_const_ref(p):
    '''const_ref : IDENTIFIER'''
    keys = p[1].split('.')
    thrift = thrift_stack[-1]

    if len(keys) == 1 and hasattr(thrift, keys[0]):
        p[0] = getattr(thrift, keys[0])
        return

    if len(keys) == 2 and hasattr(thrift, keys[0]):
        enum = getattr(thrift, keys[0])
        if hasattr(enum, keys[1]):
            p[0] = getattr(enum, keys[1])
            return
    raise ThriftParserError('No enum value or constant found named %r' % p[1])


def p_ttype(p):
    '''ttype : typedef
             | enum
             | struct
             | union
             | exception
             | service'''


def p_typedef(p):
    '''typedef : TYPEDEF definition_type IDENTIFIER'''
    setattr(thrift_stack[-1], p[3], p[2])


def p_enum(p):  # noqa
    '''enum : ENUM IDENTIFIER '{' enum_seq '}' '''
    setattr(thrift_stack[-1], p[2], _make_enum(p[2], p[4]))


def p_enum_seq(p):
    '''enum_seq : enum_item sep enum_seq
                | enum_item enum_seq
                |'''
    _parse_seq(p)


def p_enum_item(p):
    '''enum_item : IDENTIFIER '=' INTCONSTANT
                 | IDENTIFIER
                 |'''
    if len(p) == 4:
        p[0] = [p[1], p[3]]
    elif len(p) == 2:
        p[0] = [p[1], None]


def p_struct(p):
    '''struct : STRUCT IDENTIFIER '{' field_seq '}' '''
    setattr(thrift_stack[-1], p[2], _make_struct(p[2], p[4]))


def p_union(p):
    '''union : UNION IDENTIFIER '{' field_seq '}' '''
    setattr(thrift_stack[-1], p[2], _make_struct(p[2], p[4]))


def p_exception(p):
    '''exception : EXCEPTION IDENTIFIER '{' field_seq '}' '''
    setattr(thrift_stack[-1], p[2], _make_struct(p[2], p[4],
                                                 base_cls=TException))


def p_service(p):
    '''service : SERVICE IDENTIFIER '{' function_seq '}'
               | SERVICE IDENTIFIER EXTENDS IDENTIFIER '{' function_seq '}'
    '''
    thrift = thrift_stack[-1]

    if len(p) == 8:
        father = thrift

        for name in p[4].split('.'):
            child = getattr(father, name, None)
            if child is None:
                raise ThriftParserError('Can\'t find service %r for '
                                        'service %r to extend' %
                                        (p[4], p[2]))
            father = child

        if not hasattr(child, 'thrift_services'):
            raise ThriftParserError('Can\'t extends %r, not a service'
                                    % p[4])

        extends = child
    else:
        extends = None

    setattr(thrift, p[2], _make_service(p[2], p[len(p) - 2], extends))


def p_function(p):
    '''function : ONEWAY function_type IDENTIFIER '(' field_seq ')' throws
                | ONEWAY function_type IDENTIFIER '(' field_seq ')'
                | function_type IDENTIFIER '(' field_seq ')' throws
                | function_type IDENTIFIER '(' field_seq ')' '''

    if p[1] == 'oneway':
        oneway = True
        base = 1
    else:
        oneway = False
        base = 0

    if p[len(p) - 1] == ')':
        throws = []
    else:
        throws = p[len(p) - 1]

    p[0] = [oneway, p[base + 1], p[base + 2], p[base + 4], throws]


def p_function_seq(p):
    '''function_seq : function sep function_seq
                    | function function_seq
                    |'''
    _parse_seq(p)


def p_throws(p):
    '''throws : THROWS '(' field_seq ')' '''
    p[0] = p[3]


def p_function_type(p):
    '''function_type : field_type
                     | VOID'''
    if p[1] == 'void':
        p[0] = TType.VOID
    else:
        p[0] = p[1]


def p_field_seq(p):
    '''field_seq : field sep field_seq
                 | field field_seq
                 |'''
    _parse_seq(p)


def p_field(p):
    '''field : field_id field_req field_type IDENTIFIER
             | field_id field_req field_type IDENTIFIER '=' const_value'''

    if len(p) == 7:
        try:
            val = _cast(p[3])(p[6])
        except AssertionError:
            raise ThriftParserError(
                'Type error for field %s '
                'at line %d' % (p[4], p.lineno(4)))
    else:
        val = None

    p[0] = [p[1], p[2], p[3], p[4], val]


def p_field_id(p):
    '''field_id : INTCONSTANT ':' '''
    p[0] = p[1]


def p_field_req(p):
    '''field_req : REQUIRED
                 | OPTIONAL
                 |'''
    if len(p) == 2:
        p[0] = p[1] == 'required'
    elif len(p) == 1:
        p[0] = False  # default: required=False


def p_field_type(p):
    '''field_type : ref_type
                  | definition_type'''
    p[0] = p[1]


def p_ref_type(p):
    '''ref_type : IDENTIFIER'''
    father = thrift_stack[-1]

    for name in p[1].split('.'):
        child = getattr(father, name, None)
        if child is None:
            raise ThriftParserError('No type found: %r, at line %d' %
                                    (p[1], p.lineno(1)))

        father = child

    if hasattr(child, '_ttype'):
        p[0] = getattr(child, '_ttype'), child
    else:
        p[0] = child


def p_base_type(p):  # noqa
    '''base_type : BOOL
                 | BYTE
                 | I16
                 | I32
                 | I64
                 | DOUBLE
                 | STRING
                 | BINARY'''
    if p[1] == 'bool':
        p[0] = TType.BOOL
    if p[1] == 'byte':
        p[0] = TType.BYTE
    if p[1] == 'i16':
        p[0] = TType.I16
    if p[1] == 'i32':
        p[0] = TType.I32
    if p[1] == 'i64':
        p[0] = TType.I64
    if p[1] == 'double':
        p[0] = TType.DOUBLE
    if p[1] == 'string':
        p[0] = TType.STRING
    if p[1] == 'binary':
        p[0] = TType.BINARY


def p_container_type(p):
    '''container_type : map_type
                      | list_type
                      | set_type'''
    p[0] = p[1]


def p_map_type(p):
    '''map_type : MAP '<' field_type ',' field_type '>' '''
    p[0] = TType.MAP, (p[3], p[5])


def p_list_type(p):
    '''list_type : LIST '<' field_type '>' '''
    p[0] = TType.LIST, p[3]


def p_set_type(p):
    '''set_type : SET '<' field_type '>' '''
    p[0] = TType.SET, p[3]


def p_definition_type(p):
    '''definition_type : base_type
                       | container_type'''
    p[0] = p[1]


thrift_stack = []
include_dir_ = '.'


def parse(path, module_name=None, include_dir=None, lexer=None, parser=None):
    if lexer is None:
        lexer = lex.lex()
    if parser is None:
        parser = yacc.yacc(debug=False, write_tables=0)

    global include_dir_

    if include_dir is not None:
        include_dir_ = include_dir

    if not path.endswith('.thrift'):
        raise ThriftParserError('Path should end with .thrift')

    with open(path) as fh:
        data = fh.read()

    if module_name is not None and not module_name.endswith('_thrift'):
        raise ThriftParserError('ThriftPy can only generate module with '
                                '\'_thrift\' suffix')

    if module_name is None:
        module_name = os.path.basename(path)[:-7]

    thrift = types.ModuleType(module_name)
    thrift_stack.append(thrift)
    lexer.lineno = 1
    parser.parse(data)
    return thrift_stack.pop()


def _parse_seq(p):
    if len(p) == 4:
        p[0] = [p[1]] + p[3]
    elif len(p) == 3:
        p[0] = [p[1]] + p[2]
    elif len(p) == 1:
        p[0] = []


def _cast(t):  # noqa
    if t == TType.BOOL:
        return _cast_bool
    if t == TType.BYTE:
        return _cast_byte
    if t == TType.I16:
        return _cast_i16
    if t == TType.I32:
        return _cast_i32
    if t == TType.I64:
        return _cast_i64
    if t == TType.DOUBLE:
        return _cast_double
    if t == TType.STRING:
        return _cast_string
    if t == TType.BINARY:
        return _cast_binary
    if t[0] == TType.LIST:
        return _cast_list(t)
    if t[0] == TType.SET:
        return _cast_set(t)
    if t[0] == TType.MAP:
        return _cast_map(t)
    if t[0] == TType.I32:
        return _cast_enum(t)
    if t[0] == TType.STRUCT:
        return _cast_struct(t)


def _cast_bool(v):
    assert isinstance(v, bool)
    return v


def _cast_byte(v):
    assert isinstance(v, str)
    return v


def _cast_i16(v):
    assert isinstance(v, int)
    return v


def _cast_i32(v):
    assert isinstance(v, int)
    return v


def _cast_i64(v):
    assert isinstance(v, int)
    return v


def _cast_double(v):
    assert isinstance(v, float)
    return v


def _cast_string(v):
    assert isinstance(v, str)
    return v


def _cast_binary(v):
    assert isinstance(v, str)
    return v


def _cast_list(t):
    assert t[0] == TType.LIST

    def __cast_list(v):
        assert isinstance(v, list)
        map(_cast(t[1]), v)
        return v
    return __cast_list


def _cast_set(t):
    assert t[0] == TType.SET

    def __cast_set(v):
        assert isinstance(v, (list, set))
        map(_cast(t[1]), v)
        if not isinstance(v, set):
            return set(v)
        return v
    return __cast_set


def _cast_map(t):
    assert t[0] == TType.MAP

    def __cast_map(v):
        assert isinstance(v, dict)
        for key in v:
            v[_cast(t[1][0])(key)] = \
                _cast(t[1][1])(v[key])
        return v
    return __cast_map


def _cast_enum(t):
    assert t[0] == TType.I32

    def __cast_enum(v):
        assert isinstance(v, int)
        if v in getattr(t[1], '_named_values'):
            return v
        raise ThriftParserError('Couldn\'t find a named value in enum '
                                '%s for value %d' % (t[1].__name__, v))
    return __cast_enum


def _cast_struct(t):   # struct/exception/union
    assert t[0] == TType.STRUCT

    def __cast_struct(v):
        if isinstance(v, t[1]):
            return v  # already cast

        assert isinstance(v, dict)
        tspec = getattr(t[1], '_tspec')

        for key in tspec:  # requirement check
            if tspec[key][0] and key not in v:
                raise ThriftParserError('Field %r was required to create '
                                        'constant for type %r' %
                                        (key, t[1].__name__))

        for key in v:  # cast values
            if key not in tspec:
                raise ThriftParserError('No field named %r was '
                                        'found in struct of type %r' %
                                        (key, t[1].__name__))
            v[key] = _cast(tspec[key][1])(v[key])
        return t[1](**v)
    return __cast_struct


def _make_enum(name, kvs):
    attrs = {'__module__': thrift_stack[-1].__name__, '_ttype': TType.I32}
    cls = type(name, (object, ), attrs)
    named_values = set()
    for key, val in kvs:
        if val is not None:
            named_values.add(val)
    setattr(cls, '_named_values', named_values)

    if kvs:
        val = kvs[0][1]
        if val is None:
            val = -1
        for item in kvs:
            if item[1] is None:
                item[1] = val + 1
            val = item[1]
        for key, val in kvs:
            setattr(cls, key, val)
    return cls


def _make_struct(name, fields, ttype=TType.STRUCT, base_cls=TPayload):
    attrs = {'__module__': thrift_stack[-1].__name__, '_ttype': ttype}
    cls = type(name, (base_cls, ), attrs)
    thrift_spec = {}
    default_spec = []
    _tspec = {}

    for field in fields:
        ttype = field[2]
        thrift_spec[field[0]] = _ttype_spec(ttype, field[3], field[1])
        default_spec.append((field[3], field[4]))
        _tspec[field[3]] = field[1], ttype
    setattr(cls, 'thrift_spec', thrift_spec)
    setattr(cls, 'default_spec', default_spec)
    setattr(cls, '_tspec', _tspec)
    gen_init(cls, thrift_spec, default_spec)
    return cls


def _make_service(name, funcs, extends):
    if extends is None:
        extends = object

    attrs = {'__module__': thrift_stack[-1].__name__}
    cls = type(name, (extends, ), attrs)
    thrift_services = []

    for func in funcs:
        func_name = func[2]
        # args payload cls
        args_name = '%s_args' % func_name
        args_fields = func[3]
        args_cls = _make_struct(args_name, args_fields)
        setattr(cls, args_name, args_cls)
        # result payload cls
        result_name = '%s_result' % func_name
        result_type = func[1]
        result_throws = func[4]
        result_oneway = func[0]
        result_cls = _make_struct(result_name, result_throws)
        setattr(result_cls, 'oneway', result_oneway)
        result_cls.thrift_spec[0] = _ttype_spec(result_type, 'success')
        result_cls.default_spec.insert(0, ('success', None))
        setattr(cls, result_name, result_cls)
        thrift_services.append(func_name)
    setattr(cls, 'thrift_services', thrift_services)
    return cls


def _ttype_spec(ttype, name, required=False):
    if isinstance(ttype, int):
        return ttype, name, required
    else:
        return ttype[0], name, ttype[1], required
