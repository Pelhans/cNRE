#!/usr/bin/env python
# coding=utf-8
import json
import numpy as np
from collections import OrderedDict
import random

class BatchGenerator(object):
    """Construct a Data generator. THe input is json files
        file_name: Json file storing the data in the following format
            [
                {
                    'sentence': 'Bill Gates is the founder of Microsoft .',
                    'head': {'word': 'Bill Gates', ...(other information)},
                    'tail': {'word': 'Microsoft', ...(other information)},
                    'relation': 'founder'
                },
                ...
            ]
            #*IMPORTANT: In the sentence part, words and punctuations should be separated by blank spaces.
        word_vec_file_name: Json file storing word vectors in the following format
            [
                {'word': 'the', 'vec': [0.418, 0.24968, ...]},
                {'word': ',', 'vec': [0.013441, 0.23682, ...]},
                ...
            ]
        rel2id_file_name: Json file storing relation-to-id diction in the following format
            {
                'NA': 0
                'founder': 1
                ...
            }
            #*IMPORTANT: make sure the id of NA is 0.
    """

    def __init__(self, file_name, word_vec_file_name, rel2id_file_name, mode="train", max_length=120, batch_size=160, shuffle=True):
        self.mode = mode
        self.max_length = max_length
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.ori_data = json.load(open(file_name, "r"))
        self.rel2id = json.load(open(rel2id_file_name))
        self.rel_tot = len(self.rel2id)
        word_vec = json.load(open(word_vec_file_name))
        self.instance_tot = len(self.ori_data)
        self.data_rel = np.zeros((self.instance_tot), dtype=np.int32)
        self.idx = 0
        self.relfact_tot = 0
        self.instance_vec = []
        self.pos1 = []
        self.pos2 = []
        self.bag_data = []
        self._length = []
        self.entpair = []
        
        # Build word dicttionary
        self.word_dict = {w["word"] : w["vec"] for w in word_vec}
        self.word_dict["UNK"] = np.ones((len(self.word_dict[self.word_dict.keys()[0]])), dtype=np.float32)
        self.word_dict["BLANK"] = np.ones((len(self.word_dict[self.word_dict.keys()[0]])), dtype=np.float32)
#        self.word_dict["BLANK"] = np.ones((len(word_vec)), dtype=np.float32)
        self.word2id = {w : i for i,w in enumerate(self.word_dict)}
        self.ori_data.sort(key=lambda x: x["head"]["word"] + "#" + x["tail"]["word"] + "#" + x["relation"])
        self.word_vec_mat = np.zeros((len(self.word_dict), len(self.word_dict[self.word_dict.keys()[0]])), dtype=np.float32)

        # Convert each instance into vector
        for idx, instance in enumerate(self.ori_data):
            words = instance["sentence"].strip().split()
            self.data_rel[idx] = self.rel2id[instance["relation"]] if instance["relation"] in self.rel2id else self.rel2id["NA"]
            vecs = [self.word2id[w] if w in self.word2id else self.word2id["UNK"]  for w in words ]
            self._length.append(len(vecs))
            vecs = self._padding(vecs, content=self.word2id["BLANK"])
            self.instance_vec.append(vecs)

        # Calculate the distance of a word from an entity
        self.pos1 = [self._cal_distance(instance, pos="head") for instance in self.ori_data]
        self.pos2 = [self._cal_distance(instance, pos="tail") for instance in self.ori_data]

        # Package an instance of the same relationship
        self.bag_data, self.label, self.bag_pos1, self.bag_pos2, self.length, self.scope, self.entpair = self._scope(self.ori_data)
        self.out_order = self.bag_data.keys()
        if self.shuffle:
            random.shuffle(self.out_order)

    def _word_vec_mat(self):
#        self.word_vec_mat = np.zeros((len(self.word_dict), len(self.word_dict[0])), dtype=np.float32)
        for cur_id, word in enumerate(self.word_dict):
            self.word_vec_mat[cur_id, :] = self.word_dict[word["word"]]

    def __iter__(self):
        return self

    def __next__(self):
        return self.next_batch(self.batch_size)

    def next_batch(self, batch_size):
        if self.idx >= len(self.bag_data):
            self.idx = 0
            if self.shuffle:
                random.shuffle(self.out_order)
            raise StopIteration
        
        batch_data = {}
        idx0 = self.idx
        idx1 = self.idx + batch_size
        if idx1 > len(self.out_order):
            idx1 = len(self.out_order)
        self.idx = idx1
        bag = []
        label = []
        pos1 = []
        pos2 = []
        _ins_label = []
        scope = []
        length = []
        _multi_rel = []
        _entpair = []
        cur_pos = 0
        for i in range(idx0, idx1):
            bag.append(self.bag_data[self.out_order[i]])
            label.append(self.label[self.out_order[i]])
            # Assume that the relationship tags in each package are the same
            pos1.append(self.bag_pos1[self.out_order[i]])
            pos2.append(self.bag_pos2[self.out_order[i]])
            _ins_label.append([self.label[self.out_order[i]]]*len(self.bag_data[self.out_order[i]]))
#            _ins_label.append(self.data_rel[start:idx])
            length.append(self.length[self.out_order[i]])
#            scope.append(self.scope[self.out_order[i]])
            # Scope stores the relative position in this batch
            bag_size = len(self.bag_data[self.out_order[i]])
            scope.append([cur_pos, cur_pos+bag_size])
            cur_pos += bag_size
            if self.mode == "test":
                _one_multi_rel = np.zeros((self.rel_tot), dtype=np.int32)
                iter_scope = self.scope[self.out_order[i]]
                for j in range(iter_scope[0], iter_scope[1]):
                    _one_multi_rel[self.data_rel[j]] = 1
                _multi_rel.append(_one_multi_rel)
                _entpair.append(self.entpair[self.out_order[i]])
        # If not enough for batch_size,fill it with 0
        last_scope = scope[-1][-1]
        for i in range(batch_size - (idx1-idx0)):
            bag.append(np.zeros((1, self.max_length), dtype=np.int32))
            label.append(0)
            pos1.append(np.zeros((1, self.max_length), dtype=np.int32))
            pos2.append(np.zeros((1, self.max_length), dtype=np.int32))
            _ins_label.append(np.zeros((1), dtype=np.int32))
            length.append(np.zeros((1), dtype=np.int32))
#            scope.append([last_scope, last_scope+1])
            scope.append([cur_pos, cur_pos+1])
            cur_pos += 1
            last_scope += 1
            if self.mode == "test":
                _multi_rel.append(np.zeros((self.rel_tot), dtype=np.int32))
                _entpair.append("None#None")
        batch_data["word"] = np.concatenate(bag)
        batch_data["rel"] = np.stack(label)
        batch_data["pos1"] = np.concatenate(pos1)
        batch_data["pos2"] = np.concatenate(pos2)
        batch_data["ins_rel"] = np.concatenate(_ins_label)
        batch_data["length"] = np.concatenate(length)
        batch_data["scope"] = np.stack(scope)
        if self.mode == "test":
            batch_data["multi_rel"] = np.stack(_multi_rel)
            batch_data["entpair"] = _entpair
        return batch_data

    def _scope(self, instance):
#        bag_rel_vec = OrderedDict()
        bag_rel_vec = {}
        bag_pos1_vec = {}
        bag_pos2_vec = {}
        _length = []
        label = []
        scope = []
        ent_bag = []
        start = -1
        last_key = ""
        last_relfact = ""
        last_relfact_pos = -1
        for idx, x in enumerate(instance):
            key = ""
            if self.mode == "train":
                key = x["head"]["id"] + "#" + x["tail"]["id"] + "#" + x["relation"]
            elif self.mode == "test":
                key = x["head"]["id"] + "#" + x["tail"]["id"]
            if last_key != key:
                if last_key != "":
#                    relid = self.rel2id[x["relation"]] if x["relation"] in self.rel2id else self.rel2id["NA"]
    #               bag_rel_vec[relid] = [self.instance_vec[i] for i in range(start, idx)]
                    bag_rel_vec[len(label)] = [self.instance_vec[i] for i in range(start, idx)]
                    bag_pos1_vec[len(label)] = [self.pos1[i] for i in range(start, idx)]
                    bag_pos2_vec[len(label)] = [self.pos2[i] for i in range(start, idx)]
                    label.append(self.data_rel[start])
                    _length.append([self._length[i] for i in range(start, idx)])
                    scope.append([start, idx])
                    tmp_ins = instance[start]
                    tmp_ent = tmp_ins["head"]["word"] + "#" + tmp_ins["tail"]["word"]
                    ent_bag.append(tmp_ent)
                start = idx
                last_key = key
            relfact = x["head"]["id"] + "#" + x["tail"]["id"] + "#" + x["relation"]
            if last_relfact != relfact:
                if last_relfact != "":
                    if instance[last_relfact_pos]["relation"] != "NA":
                        self.relfact_tot += 1
                last_relfact_pos = idx
                last_relfact = relfact
        print "self.relfact_tot: ", self.relfact_tot
        return bag_rel_vec, label, bag_pos1_vec, bag_pos2_vec, _length, scope, ent_bag

    def _cal_distance(self, instance, pos="head"):
        # Avoid situations where the target entity is part of another word
        sentence = instance["sentence"]
        words = sentence.strip().split()
        # char_pos is the position of the character level
        char_pos = sentence.find(" " + instance[pos]["word"] + " ")
        if char_pos != -1:
            char_pos += 1
        else:
            if sentence[:len(instance[pos]["word"])+1] == instance[pos]["word"] + " ":
                char_pos = 0
            elif sentence[-len(instance[pos]["word"])-1:] == " " + instance[pos]["word"]:
                char_pos = len(sentence) - len(instance[pos]["word"])
            else:
                char_pos = 0
        tmp_p = 0
        for idx,w in enumerate(words):
            if tmp_p == char_pos:
                pos = idx
                char_pos = -1
            tmp_p += len(w) + 1
        pos = self.max_length - 1 if pos > self.max_length else pos
        words = self._padding(words, content="BLANK")
        distance_vec = [pos-i+self.max_length for i in range(len(words))]
        return distance_vec

    def _padding(self, vec, content=0):
        """ padding the vector with content, vector's shape should be (1,).
        if content = self.word_dict["BLANK"], we will padding it with BLANK id
        else content = 0, we will padding with 0
        """
        if len(vec) > self.max_length:
            vec = vec[:self.max_length]
        else:
            vec.extend(np.full(self.max_length-len(vec), content))
        return vec


if __name__ == "__main__":
    batch = BatchGenerator("../data/mini/test.json", "../data/mini/word_vec.json", "../data/mini/rel2id.json", mode="test", batch_size=1)
#    batch = BatchGenerator("../../OpenNRE/data/nyt/test.json", "../../OpenNRE/data/nyt/word_vec.json", "../../OpenNRE/data/nyt/rel2id.json", mode="test", batch_size=1)
    print batch.next_batch(1)
#    print batch.next_batch(1)
#    print batch.next_batch(1)
